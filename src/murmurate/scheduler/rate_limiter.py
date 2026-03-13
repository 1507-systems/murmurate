"""Per-domain rate limiter backed by SQLite sliding window.

Wraps the StateDB rate-limit methods with a clean interface so the scheduler
can check and record domain requests without dealing with raw SQL or window
arithmetic directly.
"""

from murmurate.database import StateDB


class RateLimiter:
    """Enforces per-domain request rate limits using a sliding window.

    All checks are against the last 60 seconds (one minute), matching the
    rpm_limit semantics expected by callers.  Cleanup uses a wider 300-second
    window so that entries are retained slightly beyond the check window —
    useful for debugging and for avoiding spurious gaps if cleanup runs during
    a burst.
    """

    def __init__(self, db: StateDB) -> None:
        self._db = db

    async def can_request(self, domain: str, rpm_limit: int) -> bool:
        """Check if a request to *domain* is allowed under its RPM limit.

        Uses a 60-second sliding window.  Returns True when the number of
        recorded requests in the window is strictly less than *rpm_limit*.
        """
        count = await self._db.get_request_count(domain, window_seconds=60)
        return count < rpm_limit

    async def record(self, domain: str) -> None:
        """Record a request to *domain* for rate tracking."""
        await self._db.record_request(domain)

    async def cleanup(self) -> None:
        """Remove expired rate-limit entries (older than 300 seconds).

        Should be called periodically — e.g. once per scheduler tick — to
        prevent unbounded growth of the rate_limits table.  The 300-second
        max-age is intentionally wider than the 60-second check window so
        that recent data is always available for inspection.
        """
        await self._db.cleanup_rate_limits(max_age_seconds=300)
