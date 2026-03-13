"""
test_transport_pool.py — Tests for BrowserPool.

All tests use mocked Playwright objects so no real browser is required.
Covers: context creation up to max_size, context reuse, rotation on
max_sessions, rotation on max_age, timeout when pool is full, close_all
cleanup, and fresh profile isolation (no cookie bleed between contexts).
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from murmurate.transport.pool import BrowserPool, PooledContext
from murmurate.models import FingerprintProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fingerprint(seed: int = 42) -> FingerprintProfile:
    """Return a minimal FingerprintProfile for pool tests."""
    return FingerprintProfile(
        platform="Win32",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        screen_width=1920,
        screen_height=1080,
        viewport_width=1536,
        viewport_height=864,
        timezone_id="America/Chicago",
        locale="en-US",
        accept_language="en-US,en;q=0.9",
        hardware_concurrency=8,
        device_memory=16,
        webgl_vendor="Google Inc.",
        webgl_renderer="ANGLE (NVIDIA)",
        canvas_noise_seed=seed,
        fonts=["Arial", "Times New Roman"],
        created_at="2026-03-12T10:00:00Z",
        last_rotated=None,
    )


def _mock_browser():
    """Build a fully-mocked Playwright browser hierarchy."""
    browser = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    page.goto = AsyncMock()
    page.content = AsyncMock(return_value="<html><body>Hello</body></html>")
    return browser, context, page


# ---------------------------------------------------------------------------
# Pool creation and basic acquire/release
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pool_creates_context_on_first_acquire():
    """Acquiring from an empty pool should create a new browser context."""
    browser, mock_ctx, _ = _mock_browser()
    pool = BrowserPool(browser, max_size=3)

    fp = _make_fingerprint()
    pooled = await pool.acquire(fp)
    try:
        assert pooled is not None
        assert pooled.in_use is True
        assert pool.size == 1
    finally:
        await pool.release(pooled)
    await pool.close_all()


@pytest.mark.asyncio
async def test_pool_reuses_released_context():
    """After releasing a context, the next acquire should reuse it."""
    browser, mock_ctx, _ = _mock_browser()
    pool = BrowserPool(browser, max_size=3)
    fp = _make_fingerprint()

    pooled1 = await pool.acquire(fp)
    await pool.release(pooled1)

    pooled2 = await pool.acquire(fp)
    try:
        # Same underlying PooledContext object reused
        assert pooled1 is pooled2
        assert pool.size == 1  # no new context created
    finally:
        await pool.release(pooled2)
    await pool.close_all()


@pytest.mark.asyncio
async def test_pool_creates_up_to_max_size():
    """Pool should create new contexts up to max_size when all are in_use."""
    browser, _, _ = _mock_browser()
    # Each new_context call returns a fresh AsyncMock so contexts are distinct
    browser.new_context = AsyncMock(side_effect=lambda **kwargs: AsyncMock())
    pool = BrowserPool(browser, max_size=3)
    fp = _make_fingerprint()

    pooled_list = []
    for _ in range(3):
        p = await pool.acquire(fp)
        pooled_list.append(p)

    assert pool.size == 3
    # All in use
    assert pool.available == 0

    for p in pooled_list:
        await pool.release(p)
    await pool.close_all()


@pytest.mark.asyncio
async def test_pool_available_count():
    """available property should reflect free (not in_use) contexts."""
    browser, _, _ = _mock_browser()
    browser.new_context = AsyncMock(side_effect=lambda **kwargs: AsyncMock())
    pool = BrowserPool(browser, max_size=3)
    fp = _make_fingerprint()

    p1 = await pool.acquire(fp)
    p2 = await pool.acquire(fp)
    assert pool.available == 0

    await pool.release(p1)
    assert pool.available == 1

    await pool.release(p2)
    assert pool.available == 2

    await pool.close_all()


# ---------------------------------------------------------------------------
# Rotation: max_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pool_rotates_after_max_sessions():
    """A context that has hit max_sessions should be closed and replaced."""
    browser, _, _ = _mock_browser()
    # Return fresh AsyncMock contexts so we can track close() calls
    contexts = [AsyncMock() for _ in range(5)]
    context_iter = iter(contexts)
    browser.new_context = AsyncMock(side_effect=lambda **kwargs: next(context_iter))
    pool = BrowserPool(browser, max_size=1, max_sessions=2)
    fp = _make_fingerprint()

    # First context — use twice (hits max_sessions on second release)
    p = await pool.acquire(fp)
    first_context = p.context
    await pool.release(p)

    p = await pool.acquire(fp)
    assert p.context is first_context  # reused
    await pool.release(p)  # session_count == 2 → should rotate

    # After rotation, pool must have 0 contexts (the old one was closed and removed)
    # because no replacement is created until next acquire
    assert pool.size == 0

    # Next acquire creates a fresh context
    p2 = await pool.acquire(fp)
    assert p2.context is not first_context
    assert p2.session_count == 0

    await pool.release(p2)
    await pool.close_all()


@pytest.mark.asyncio
async def test_rotated_context_is_closed():
    """When a context is rotated out it must have close() called on it."""
    browser, _, _ = _mock_browser()
    mock_ctx = AsyncMock()
    fresh_ctx = AsyncMock()
    call_count = 0

    async def new_ctx(**kwargs):
        nonlocal call_count
        call_count += 1
        return mock_ctx if call_count == 1 else fresh_ctx

    browser.new_context = new_ctx
    pool = BrowserPool(browser, max_size=1, max_sessions=1)
    fp = _make_fingerprint()

    p = await pool.acquire(fp)
    await pool.release(p)  # session_count == 1 → rotate; close() must be called

    mock_ctx.close.assert_awaited_once()
    await pool.close_all()


# ---------------------------------------------------------------------------
# Rotation: max_age_s
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pool_rotates_after_max_age():
    """A context older than max_age_s should be rotated out on release."""
    browser, _, _ = _mock_browser()
    old_ctx = AsyncMock()
    new_ctx_mock = AsyncMock()
    calls = []

    async def new_ctx(**kwargs):
        ctx = AsyncMock()
        calls.append(ctx)
        return ctx

    browser.new_context = new_ctx
    # Very short max age
    pool = BrowserPool(browser, max_size=1, max_sessions=100, max_age_s=0.01)
    fp = _make_fingerprint()

    p = await pool.acquire(fp)
    first_ctx = p.context

    # Force the context to appear old
    p.created_at = time.monotonic() - 1.0

    await pool.release(p)  # age > max_age_s → should rotate

    assert pool.size == 0
    first_ctx.close.assert_awaited_once()
    await pool.close_all()


# ---------------------------------------------------------------------------
# Timeout when pool is full
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pool_raises_timeout_when_full():
    """When pool is at max_size and all contexts are in_use, acquire should timeout."""
    browser, _, _ = _mock_browser()
    browser.new_context = AsyncMock(side_effect=lambda **kwargs: AsyncMock())
    pool = BrowserPool(browser, max_size=2, acquire_timeout_s=0.1)
    fp = _make_fingerprint()

    # Fill the pool
    p1 = await pool.acquire(fp)
    p2 = await pool.acquire(fp)

    # Now pool is full and both in use — next acquire should timeout
    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await pool.acquire(fp)

    await pool.release(p1)
    await pool.release(p2)
    await pool.close_all()


# ---------------------------------------------------------------------------
# close_all
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_all_closes_every_context():
    """close_all() should close all tracked contexts and clear the list."""
    browser, _, _ = _mock_browser()
    contexts = [AsyncMock() for _ in range(3)]
    ctx_iter = iter(contexts)
    browser.new_context = AsyncMock(side_effect=lambda **kwargs: next(ctx_iter))
    pool = BrowserPool(browser, max_size=3)
    fp = _make_fingerprint()

    # Acquire and release three contexts
    pooled_list = []
    for _ in range(3):
        p = await pool.acquire(fp)
        pooled_list.append(p)
    for p in pooled_list:
        await pool.release(p)

    await pool.close_all()

    for ctx in contexts:
        ctx.close.assert_awaited_once()

    assert pool.size == 0


@pytest.mark.asyncio
async def test_close_all_on_empty_pool_is_safe():
    """close_all() on an already-empty pool must not raise."""
    browser, _, _ = _mock_browser()
    pool = BrowserPool(browser, max_size=3)
    # Should complete without exception
    await pool.close_all()
    assert pool.size == 0


# ---------------------------------------------------------------------------
# Fresh profile isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_context_has_zero_session_count():
    """Newly created PooledContext objects always start with session_count = 0."""
    browser, _, _ = _mock_browser()
    pool = BrowserPool(browser, max_size=3)
    fp = _make_fingerprint()

    pooled = await pool.acquire(fp)
    try:
        assert pooled.session_count == 0
    finally:
        await pool.release(pooled)
    await pool.close_all()


@pytest.mark.asyncio
async def test_session_count_increments_on_release():
    """Each release should increment session_count by 1."""
    browser, _, _ = _mock_browser()
    pool = BrowserPool(browser, max_size=1, max_sessions=100)
    fp = _make_fingerprint()

    p = await pool.acquire(fp)
    assert p.session_count == 0
    await pool.release(p)
    assert p.session_count == 1

    p = await pool.acquire(fp)
    assert p.session_count == 1  # same object
    await pool.release(p)
    assert p.session_count == 2

    await pool.close_all()


@pytest.mark.asyncio
async def test_rotated_contexts_are_independent():
    """After rotation, the replacement context has its own state (no bleed)."""
    browser, _, _ = _mock_browser()
    call_num = 0

    async def new_ctx(**kwargs):
        nonlocal call_num
        call_num += 1
        ctx = AsyncMock()
        ctx.name = f"ctx-{call_num}"
        return ctx

    browser.new_context = new_ctx
    pool = BrowserPool(browser, max_size=1, max_sessions=1)
    fp = _make_fingerprint()

    p1 = await pool.acquire(fp)
    await pool.release(p1)  # rotation happens here (session_count == max_sessions)

    p2 = await pool.acquire(fp)
    try:
        # p2 is a brand-new PooledContext, not reusing p1
        assert p2 is not p1
        assert p2.session_count == 0
        assert p2.context.name != p1.context.name
    finally:
        await pool.release(p2)
    await pool.close_all()
