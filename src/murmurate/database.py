# database.py — SQLite state database for session tracking and rate limiting
#
# Uses aiosqlite for non-blocking async access to a local SQLite file.
# All public methods retry on OperationalError (database locked) with
# exponential backoff — SQLite only allows one writer at a time, so brief
# contention under load is normal and retryable.

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# How many times to retry a locked-database error before giving up
_MAX_RETRIES = 3
# Base delay in seconds for the first retry; doubles on each subsequent attempt
_RETRY_BASE_DELAY = 0.05


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (with timezone suffix)."""
    return datetime.now(timezone.utc).isoformat()


class StateDB:
    """Async SQLite wrapper for murmurate session and rate-limit state.

    Usage::

        db = StateDB("state.db")
        await db.initialize()   # creates tables on first run
        ...
        await db.close()

    Pass ``":memory:"`` as the path for an in-memory database (useful in tests).
    """

    def __init__(self, db_path: str = "state.db") -> None:
        self._db_path = db_path
        # _conn is set by initialize(); declared here for type-checker visibility
        self._conn: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _execute(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        commit: bool = False,
    ) -> aiosqlite.Cursor:
        """Execute *sql* with retry logic for OperationalError (database locked).

        SQLite serialises writes; under concurrent load the database may be
        momentarily locked.  Rather than propagating that transient error we
        wait briefly and retry, up to _MAX_RETRIES times.
        """
        assert self._conn is not None, "StateDB not initialised — call initialize() first"

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                cursor = await self._conn.execute(sql, params)
                if commit:
                    await self._conn.commit()
                return cursor
            except aiosqlite.OperationalError as exc:
                last_exc = exc
                # Only retry on locking errors; re-raise anything else immediately
                if "locked" not in str(exc).lower():
                    raise
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Database locked on attempt %d/%d, retrying in %.2fs: %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

        # All retries exhausted
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open the database connection and create tables if they don't exist.

        Safe to call multiple times — CREATE TABLE IF NOT EXISTS is idempotent.
        """
        self._conn = await aiosqlite.connect(self._db_path)
        # Return rows as dict-like objects rather than plain tuples
        self._conn.row_factory = aiosqlite.Row

        await self._execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id              TEXT PRIMARY KEY,
                persona_name    TEXT NOT NULL,
                plugin_name     TEXT NOT NULL,
                transport_type  TEXT NOT NULL,
                queries_executed INTEGER,
                results_browsed  INTEGER,
                duration_s       REAL,
                machine_id      TEXT NOT NULL,
                started_at      TEXT NOT NULL,
                completed_at    TEXT,
                status          TEXT DEFAULT 'running'
            )
            """,
            commit=True,
        )

        await self._execute(
            """
            CREATE TABLE IF NOT EXISTS rate_limits (
                domain       TEXT NOT NULL,
                request_time TEXT NOT NULL,
                PRIMARY KEY (domain, request_time)
            )
            """,
            commit=True,
        )

        await self._execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rate_limits_domain_time
                ON rate_limits (domain, request_time)
            """,
            commit=True,
        )

    async def close(self) -> None:
        """Close the underlying database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Session methods
    # ------------------------------------------------------------------

    async def log_session_start(
        self,
        session_id: str,
        persona_name: str,
        plugin_name: str,
        transport_type: str,
        machine_id: str,
    ) -> None:
        """Insert a new session row with status='running' and started_at=now."""
        await self._execute(
            """
            INSERT INTO sessions
                (id, persona_name, plugin_name, transport_type,
                 machine_id, started_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'running')
            """,
            (session_id, persona_name, plugin_name, transport_type,
             machine_id, _now_iso()),
            commit=True,
        )

    async def log_session_complete(
        self,
        session_id: str,
        queries_executed: int,
        results_browsed: int,
        duration_s: float,
    ) -> None:
        """Mark a session as completed, recording its final metrics."""
        await self._execute(
            """
            UPDATE sessions
            SET status           = 'completed',
                completed_at     = ?,
                queries_executed = ?,
                results_browsed  = ?,
                duration_s       = ?
            WHERE id = ?
            """,
            (_now_iso(), queries_executed, results_browsed, duration_s, session_id),
            commit=True,
        )

    async def log_session_failed(self, session_id: str, error_msg: str) -> None:
        """Mark a session as failed.

        The error message is logged at WARNING level for observability;
        storing it in the DB is left for a future schema revision.
        """
        logger.warning("Session %s failed: %s", session_id, error_msg)
        await self._execute(
            "UPDATE sessions SET status = 'failed' WHERE id = ?",
            (session_id,),
            commit=True,
        )

    async def get_session(self, session_id: str) -> dict | None:
        """Return the session row as a plain dict, or None if not found."""
        cursor = await self._execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def get_session_history(self, limit: int = 50) -> list[dict]:
        """Return up to *limit* sessions ordered by started_at descending (newest first)."""
        cursor = await self._execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Rate-limit methods
    # ------------------------------------------------------------------

    async def record_request(self, domain: str) -> None:
        """Record that a request was made to *domain* right now.

        Uses INSERT OR IGNORE so that if two requests happen within the same
        microsecond (practically impossible, but safe) they don't raise.
        """
        await self._execute(
            "INSERT OR IGNORE INTO rate_limits (domain, request_time) VALUES (?, ?)",
            (domain, _now_iso()),
            commit=True,
        )

    async def get_request_count(self, domain: str, window_seconds: int = 60) -> int:
        """Return the number of recorded requests for *domain* in the last *window_seconds*."""
        # Build the threshold timestamp in the same format as stored values
        from datetime import timedelta
        threshold = (
            datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        ).isoformat()

        cursor = await self._execute(
            """
            SELECT COUNT(*) FROM rate_limits
            WHERE domain = ? AND request_time >= ?
            """,
            (domain, threshold),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def cleanup_rate_limits(self, max_age_seconds: int = 3600) -> None:
        """Delete rate-limit entries older than *max_age_seconds*.

        Called periodically to prevent unbounded growth of the rate_limits table.
        """
        from datetime import timedelta
        threshold = (
            datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        ).isoformat()

        await self._execute(
            "DELETE FROM rate_limits WHERE request_time < ?",
            (threshold,),
            commit=True,
        )
