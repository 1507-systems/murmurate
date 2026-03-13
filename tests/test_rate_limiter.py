import pytest
from murmurate.scheduler.rate_limiter import RateLimiter
from murmurate.database import StateDB

@pytest.fixture
async def db(tmp_path):
    database = StateDB(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()

@pytest.fixture
async def limiter(db):
    return RateLimiter(db)

@pytest.mark.asyncio
async def test_under_limit_allows(limiter):
    assert await limiter.can_request("example.com", rpm_limit=10) is True

@pytest.mark.asyncio
async def test_at_limit_blocks(limiter):
    for _ in range(10):
        await limiter.record("example.com")
    assert await limiter.can_request("example.com", rpm_limit=10) is False

@pytest.mark.asyncio
async def test_different_domains_independent(limiter):
    for _ in range(10):
        await limiter.record("example.com")
    # example.com at limit, but other.com should be fine
    assert await limiter.can_request("example.com", rpm_limit=10) is False
    assert await limiter.can_request("other.com", rpm_limit=10) is True

@pytest.mark.asyncio
async def test_record_increments_count(limiter):
    await limiter.record("test.com")
    await limiter.record("test.com")
    await limiter.record("test.com")
    assert await limiter.can_request("test.com", rpm_limit=3) is False
    assert await limiter.can_request("test.com", rpm_limit=4) is True

@pytest.mark.asyncio
async def test_cleanup_removes_old(limiter, db):
    await limiter.record("old.com")
    await limiter.cleanup()
    # Fresh records shouldn't be cleaned up yet (they're < 300s old)
    assert await limiter.can_request("old.com", rpm_limit=1) is False
