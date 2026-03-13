# test_database.py — tests for the SQLite state database (StateDB)
# All tests are async (pytest-asyncio in auto mode handles this automatically).
# Each test gets its own in-memory database to ensure isolation.

import pytest
import aiosqlite
from murmurate.database import StateDB


@pytest.fixture
async def db():
    """Provide a fresh in-memory StateDB for each test, initialized and cleaned up."""
    state_db = StateDB(":memory:")
    await state_db.initialize()
    yield state_db
    await state_db.close()


async def test_initialize_creates_tables(db):
    """After initialize(), both required tables must exist in the schema."""
    async with aiosqlite.connect(":memory:") as conn:
        # Use a separate connection to verify via a fresh DB instance
        pass

    # Verify via the db's internal connection that tables exist
    async with aiosqlite.connect(":memory:") as fresh:
        new_db = StateDB(":memory:")
        await new_db.initialize()

        async with new_db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            tables = {row[0] async for row in cursor}

        await new_db.close()

    assert "sessions" in tables
    assert "rate_limits" in tables


async def test_log_session_start_and_get(db):
    """log_session_start() should insert a row retrievable via get_session()."""
    await db.log_session_start(
        session_id="sess-001",
        persona_name="casual_browser",
        plugin_name="bing_search",
        transport_type="http",
        machine_id="roguenode",
    )

    session = await db.get_session("sess-001")

    assert session is not None
    assert session["id"] == "sess-001"
    assert session["persona_name"] == "casual_browser"
    assert session["plugin_name"] == "bing_search"
    assert session["transport_type"] == "http"
    assert session["machine_id"] == "roguenode"
    assert session["status"] == "running"
    assert session["started_at"] is not None
    assert session["completed_at"] is None


async def test_complete_session(db):
    """log_session_complete() should update status, metrics, and completed_at."""
    await db.log_session_start(
        session_id="sess-002",
        persona_name="news_reader",
        plugin_name="google_search",
        transport_type="browser",
        machine_id="roguenode",
    )

    await db.log_session_complete(
        session_id="sess-002",
        queries_executed=5,
        results_browsed=12,
        duration_s=47.3,
    )

    session = await db.get_session("sess-002")

    assert session["status"] == "completed"
    assert session["queries_executed"] == 5
    assert session["results_browsed"] == 12
    assert abs(session["duration_s"] - 47.3) < 0.001
    assert session["completed_at"] is not None


async def test_failed_session(db):
    """log_session_failed() should set status to 'failed'."""
    await db.log_session_start(
        session_id="sess-003",
        persona_name="shopper",
        plugin_name="amazon_search",
        transport_type="http",
        machine_id="roguenode",
    )

    await db.log_session_failed("sess-003", "Connection timeout after 30s")

    session = await db.get_session("sess-003")

    assert session["status"] == "failed"


async def test_get_session_nonexistent(db):
    """get_session() should return None for an ID that doesn't exist."""
    result = await db.get_session("does-not-exist")
    assert result is None


async def test_rate_limit_record_and_count(db):
    """Recording 10 requests for a domain should yield a count of 10 in the window."""
    domain = "example.com"

    for _ in range(10):
        await db.record_request(domain)

    count = await db.get_request_count(domain, window_seconds=60)

    assert count == 10


async def test_rate_limit_count_different_domains(db):
    """Request counts should be isolated per domain."""
    for _ in range(5):
        await db.record_request("alpha.com")
    for _ in range(3):
        await db.record_request("beta.com")

    assert await db.get_request_count("alpha.com", window_seconds=60) == 5
    assert await db.get_request_count("beta.com", window_seconds=60) == 3


async def test_rate_limit_cleanup(db):
    """cleanup_rate_limits() should remove entries older than max_age_seconds."""
    import asyncio
    from datetime import datetime, timezone, timedelta

    domain = "cleanup-test.com"

    # Insert a stale entry directly with an old timestamp
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
    await db._conn.execute(
        "INSERT INTO rate_limits (domain, request_time) VALUES (?, ?)",
        (domain, old_time),
    )
    await db._conn.commit()

    # Insert a fresh entry via the normal method
    await db.record_request(domain)

    # Confirm 2 entries exist before cleanup
    count_before = await db.get_request_count(domain, window_seconds=86400)
    assert count_before == 2

    # Cleanup entries older than 3600 seconds — should remove only the old one
    await db.cleanup_rate_limits(max_age_seconds=3600)

    count_after = await db.get_request_count(domain, window_seconds=86400)
    assert count_after == 1


async def test_session_history_ordering_and_limit(db):
    """get_session_history() should return sessions newest-first, honoring limit."""
    for i in range(5):
        await db.log_session_start(
            session_id=f"hist-{i:03d}",
            persona_name="persona",
            plugin_name="plugin",
            transport_type="http",
            machine_id="roguenode",
        )

    history = await db.get_session_history(limit=3)

    assert len(history) == 3
    # Newest first: hist-004, hist-003, hist-002
    assert history[0]["id"] == "hist-004"
    assert history[1]["id"] == "hist-003"
    assert history[2]["id"] == "hist-002"


async def test_session_history_default_limit(db):
    """get_session_history() default limit of 50 should not exceed total sessions."""
    for i in range(10):
        await db.log_session_start(
            session_id=f"def-{i:03d}",
            persona_name="p",
            plugin_name="pl",
            transport_type="http",
            machine_id="roguenode",
        )

    history = await db.get_session_history()
    assert len(history) == 10
