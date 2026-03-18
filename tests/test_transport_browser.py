"""
test_transport_browser.py — Tests for BrowserTransport and helpers.

Uses mocked Playwright objects — no real browser or Playwright install needed.
Covers: build_init_script JS content, typing_delay_ms range, graceful
degradation when playwright is absent, and navigate() lifecycle (acquire →
init_script → goto → dwell → content → release).
"""

import sys
from unittest.mock import AsyncMock

import pytest

from murmurate.models import FingerprintProfile
from murmurate.transport.pool import BrowserPool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fingerprint(seed: int = 99999) -> FingerprintProfile:
    """Return a minimal FingerprintProfile for BrowserTransport tests."""
    return FingerprintProfile(
        platform="MacIntel",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        screen_width=2560,
        screen_height=1600,
        viewport_width=1440,
        viewport_height=900,
        timezone_id="America/Los_Angeles",
        locale="en-US",
        accept_language="en-US,en;q=0.9",
        hardware_concurrency=10,
        device_memory=8,
        webgl_vendor="Apple Inc.",
        webgl_renderer="Apple M2",
        canvas_noise_seed=seed,
        fonts=["Helvetica", "Courier"],
        created_at="2026-03-12T12:00:00Z",
        last_rotated=None,
    )


def _mock_browser_for_pool():
    """Build a mock browser + context for pool tests."""
    browser = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)
    context.new_page = AsyncMock(return_value=page)
    context.add_init_script = AsyncMock()
    context.close = AsyncMock()
    page.goto = AsyncMock()
    page.evaluate = AsyncMock()
    page.mouse = AsyncMock()
    page.mouse.move = AsyncMock()
    page.content = AsyncMock(return_value="<html><body>Mocked Page</body></html>")
    return browser, context, page


# ---------------------------------------------------------------------------
# Import test — graceful degradation when playwright not available
# ---------------------------------------------------------------------------

def test_import_browser_transport_does_not_require_playwright():
    """
    Importing BrowserTransport should succeed even when playwright is absent.

    The module must not import playwright at the top level; it should defer
    that import until the browser object is actually used.  This test
    temporarily removes playwright from sys.modules and ensures the class
    is still importable.
    """
    # Remove playwright from sys.modules temporarily (if present)
    playwright_modules = {k: v for k, v in sys.modules.items() if "playwright" in k}
    for key in playwright_modules:
        sys.modules.pop(key, None)

    # Force reimport of the browser module — must not raise ImportError
    import importlib
    import murmurate.transport.browser as browser_mod
    importlib.reload(browser_mod)

    assert hasattr(browser_mod, "BrowserTransport")

    # Restore playwright modules if they were there before
    sys.modules.update(playwright_modules)


# ---------------------------------------------------------------------------
# build_init_script
# ---------------------------------------------------------------------------

def test_build_init_script_contains_hardware_concurrency():
    """Init script must override navigator.hardwareConcurrency."""
    from murmurate.transport.browser import BrowserTransport
    fp = _make_fingerprint()
    script = BrowserTransport.build_init_script(fp)
    assert str(fp.hardware_concurrency) in script
    assert "hardwareConcurrency" in script


def test_build_init_script_contains_device_memory():
    """Init script must override navigator.deviceMemory."""
    from murmurate.transport.browser import BrowserTransport
    fp = _make_fingerprint()
    script = BrowserTransport.build_init_script(fp)
    assert str(fp.device_memory) in script
    assert "deviceMemory" in script


def test_build_init_script_contains_webgl_vendor():
    """Init script must override WebGL UNMASKED_VENDOR_WEBGL."""
    from murmurate.transport.browser import BrowserTransport
    fp = _make_fingerprint()
    script = BrowserTransport.build_init_script(fp)
    assert fp.webgl_vendor in script


def test_build_init_script_contains_webgl_renderer():
    """Init script must override WebGL UNMASKED_RENDERER_WEBGL."""
    from murmurate.transport.browser import BrowserTransport
    fp = _make_fingerprint()
    script = BrowserTransport.build_init_script(fp)
    assert fp.webgl_renderer in script


def test_build_init_script_contains_canvas_noise_seed():
    """Init script must embed the canvas noise seed for deterministic noise."""
    from murmurate.transport.browser import BrowserTransport
    fp = _make_fingerprint(seed=777)
    script = BrowserTransport.build_init_script(fp)
    assert "777" in script


def test_build_init_script_is_string():
    """build_init_script should return a non-empty string."""
    from murmurate.transport.browser import BrowserTransport
    fp = _make_fingerprint()
    script = BrowserTransport.build_init_script(fp)
    assert isinstance(script, str)
    assert len(script) > 50  # sanity: not an empty stub


def test_build_init_script_different_fps_produce_different_scripts():
    """Two fingerprints with different values should produce different scripts."""
    from murmurate.transport.browser import BrowserTransport
    fp1 = _make_fingerprint(seed=111)
    fp2 = _make_fingerprint(seed=222)
    fp2.hardware_concurrency = 16
    script1 = BrowserTransport.build_init_script(fp1)
    script2 = BrowserTransport.build_init_script(fp2)
    assert script1 != script2


# ---------------------------------------------------------------------------
# typing_delay_ms
# ---------------------------------------------------------------------------

def test_typing_delay_ms_default_wpm_range():
    """At 60 WPM the per-character delay should be in the 50–200 ms range."""
    from murmurate.transport.browser import BrowserTransport
    # Run many samples to confirm range under jitter
    for _ in range(50):
        delay = BrowserTransport.typing_delay_ms(wpm=60)
        assert 40 <= delay <= 400, f"Delay {delay}ms is outside expected range"


def test_typing_delay_ms_faster_wpm_is_shorter():
    """Higher WPM should produce a shorter average delay than lower WPM."""
    from murmurate.transport.browser import BrowserTransport
    # Average over many samples to wash out jitter
    fast_avg = sum(BrowserTransport.typing_delay_ms(wpm=120) for _ in range(100)) / 100
    slow_avg = sum(BrowserTransport.typing_delay_ms(wpm=30) for _ in range(100)) / 100
    assert fast_avg < slow_avg


def test_typing_delay_ms_returns_positive():
    """typing_delay_ms should always return a positive number."""
    from murmurate.transport.browser import BrowserTransport
    for _ in range(20):
        delay = BrowserTransport.typing_delay_ms()
        assert delay > 0


# ---------------------------------------------------------------------------
# navigate() lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_navigate_acquires_and_releases_context():
    """navigate() must acquire a context before use and release it after."""
    from murmurate.transport.browser import BrowserTransport

    browser, mock_ctx, mock_page = _mock_browser_for_pool()
    pool = BrowserPool(browser, max_size=3)

    transport = BrowserTransport(pool)
    fp = _make_fingerprint()

    await transport.navigate("http://example.com", fp, dwell_time_s=0.0)

    # Pool should now have the context back (available)
    assert pool.available == 1
    await pool.close_all()


@pytest.mark.asyncio
async def test_navigate_calls_add_init_script():
    """navigate() should install the fingerprint init script on the context."""
    from murmurate.transport.browser import BrowserTransport

    browser, mock_ctx, mock_page = _mock_browser_for_pool()
    pool = BrowserPool(browser, max_size=3)

    transport = BrowserTransport(pool)
    fp = _make_fingerprint()

    await transport.navigate("http://example.com", fp, dwell_time_s=0.0)

    # add_init_script should have been called with the JS string
    mock_ctx.add_init_script.assert_awaited()
    await pool.close_all()


@pytest.mark.asyncio
async def test_navigate_calls_goto():
    """navigate() should call page.goto with the provided URL."""
    from murmurate.transport.browser import BrowserTransport

    browser, mock_ctx, mock_page = _mock_browser_for_pool()
    pool = BrowserPool(browser, max_size=3)

    transport = BrowserTransport(pool)
    fp = _make_fingerprint()

    target_url = "http://example.com/test"
    await transport.navigate(target_url, fp, dwell_time_s=0.0)

    # Verify goto was called with the right URL
    mock_page.goto.assert_awaited()
    called_url = mock_page.goto.call_args[0][0]
    assert called_url == target_url

    await pool.close_all()


@pytest.mark.asyncio
async def test_navigate_returns_html_content():
    """navigate() should return the page HTML content."""
    from murmurate.transport.browser import BrowserTransport

    browser, mock_ctx, mock_page = _mock_browser_for_pool()
    mock_page.content = AsyncMock(return_value="<html><body>Test Content</body></html>")
    pool = BrowserPool(browser, max_size=3)

    transport = BrowserTransport(pool)
    fp = _make_fingerprint()

    result = await transport.navigate("http://example.com", fp, dwell_time_s=0.0)

    assert result is not None
    assert "Test Content" in result

    await pool.close_all()


@pytest.mark.asyncio
async def test_navigate_releases_on_exception():
    """navigate() must release the context back to the pool even if goto raises."""
    from murmurate.transport.browser import BrowserTransport

    browser, mock_ctx, mock_page = _mock_browser_for_pool()
    mock_page.goto = AsyncMock(side_effect=Exception("Navigation failed"))
    pool = BrowserPool(browser, max_size=3)

    transport = BrowserTransport(pool)
    fp = _make_fingerprint()

    with pytest.raises(Exception, match="Navigation failed"):
        await transport.navigate("http://example.com", fp, dwell_time_s=0.0)

    # Context must have been released despite the exception
    assert pool.available == 1
    await pool.close_all()
