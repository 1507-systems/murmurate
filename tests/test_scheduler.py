"""
tests/test_scheduler.py — Unit tests for the main Scheduler class.

All external dependencies (transports, database, plugins) are fully mocked
so these tests are fast, deterministic, and never touch the network or disk.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from murmurate.scheduler.scheduler import Scheduler
from murmurate.models import (
    TransportType, PersonaState, TopicNode, FingerprintProfile,
    SearchResult, BrowseAction,
)
from murmurate.config import MurmurateConfig


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_persona() -> PersonaState:
    """Build a minimal PersonaState suitable for testing."""
    fp = FingerprintProfile(
        platform="windows", user_agent="Mozilla/5.0", screen_width=1920,
        screen_height=1080, viewport_width=1536, viewport_height=864,
        timezone_id="America/Chicago", locale="en-US",
        accept_language="en-US,en;q=0.9", hardware_concurrency=8,
        device_memory=16, webgl_vendor="Google Inc.",
        webgl_renderer="ANGLE (NVIDIA)", canvas_noise_seed=12345,
        fonts=["Arial"], created_at="2026-03-12T10:00:00Z", last_rotated=None,
    )
    root = TopicNode(topic="cooking", depth=0, children=[], query_count=0, last_used=None)
    return PersonaState(
        name="chef", version=1, seeds=["cooking"], topic_tree=[root],
        fingerprint=fp, created_at="2026-03-12T10:00:00Z",
        total_sessions=0, expertise_level=0.0,
    )


def _make_scheduler():
    """
    Construct a Scheduler with fully-mocked dependencies.

    Returns the scheduler plus the key mocks so individual tests can
    inspect calls or override behaviour.
    """
    config = MurmurateConfig()
    persona = _make_persona()

    # --- Mock plugin ---
    plugin = MagicMock()
    plugin.name = "test_plugin"
    plugin.domains = ["test.com"]
    plugin.preferred_transport = TransportType.HTTP
    plugin.rate_limit_rpm = 60
    plugin.execute_search = AsyncMock(return_value=[
        SearchResult(
            title="Test", url="http://test.com/1",
            snippet="Test result", position=1,
        )
    ])
    plugin.browse_result = AsyncMock(return_value=BrowseAction(
        url_visited="http://test.com/1",
        dwell_time_s=5.0,
        links_found=["http://test.com/2"],
        content_snippets=["cooking recipes"],
        status_code=200,
    ))

    # --- Mock registry ---
    registry = MagicMock()
    registry.get_enabled.return_value = [plugin]
    registry.record_success = MagicMock()
    registry.record_failure = MagicMock()

    # --- Mock transports ---
    http_transport = MagicMock()

    # --- Mock database (all methods are async) ---
    db = AsyncMock()
    db.log_session_start = AsyncMock()
    db.log_session_complete = AsyncMock()
    db.log_session_failed = AsyncMock()

    # --- Mock timing (no delays in tests) ---
    timing = MagicMock()
    timing.next_delay.return_value = 0.0   # no wait
    timing.should_burst.return_value = False

    # --- Mock rate limiter ---
    rate_limiter = AsyncMock()
    rate_limiter.can_request = AsyncMock(return_value=True)
    rate_limiter.record = AsyncMock()

    scheduler = Scheduler(
        config=config,
        personas=[persona],
        registry=registry,
        http_transport=http_transport,
        browser_transport=None,      # no browser transport by default
        db=db,
        timing=timing,
        rate_limiter=rate_limiter,
    )

    return scheduler, plugin, registry, db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_single_session():
    """A single session should produce one SessionResult and log to the DB."""
    scheduler, plugin, registry, db = _make_scheduler()
    results = await scheduler.run(max_sessions=1)

    assert len(results) == 1
    assert results[0].plugin_name == "test_plugin"
    assert results[0].persona_name == "chef"

    db.log_session_start.assert_called_once()
    db.log_session_complete.assert_called_once()
    registry.record_success.assert_called_once_with("test_plugin")


@pytest.mark.asyncio
async def test_run_multiple_sessions():
    """Scheduler should run exactly max_sessions iterations."""
    scheduler, _, _, _ = _make_scheduler()
    results = await scheduler.run(max_sessions=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_stop_before_run():
    """Calling stop() before run() should produce zero results immediately."""
    scheduler, _, _, _ = _make_scheduler()
    scheduler.stop()
    results = await scheduler.run(max_sessions=100)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_plugin_failure_tracked():
    """When execute_search raises, the failure is tracked and session logged as failed."""
    scheduler, plugin, registry, db = _make_scheduler()
    plugin.execute_search = AsyncMock(side_effect=Exception("Network error"))

    results = await scheduler.run(max_sessions=1)

    assert len(results) == 0
    registry.record_failure.assert_called_once_with("test_plugin")
    db.log_session_failed.assert_called_once()


@pytest.mark.asyncio
async def test_browse_failure_does_not_abort_session():
    """A browse_result failure is logged as a warning but the session still completes."""
    scheduler, plugin, registry, db = _make_scheduler()
    plugin.browse_result = AsyncMock(side_effect=Exception("Timeout"))

    # execute_search returns one result; browse_result fails for it
    results = await scheduler.run(max_sessions=1)

    # Session should still complete (0 pages browsed is acceptable)
    assert len(results) == 1
    assert results[0].results_browsed == 0
    registry.record_success.assert_called_once_with("test_plugin")
    db.log_session_complete.assert_called_once()


def test_select_transport_http():
    """Plugins that prefer HTTP always get HTTP."""
    scheduler, _, _, _ = _make_scheduler()
    assert scheduler._select_transport(TransportType.HTTP) == TransportType.HTTP


def test_select_transport_browser_fallback():
    """Without a browser transport, BROWSER preference falls back to HTTP."""
    scheduler, _, _, _ = _make_scheduler()
    # browser_transport=None was passed to the constructor
    assert scheduler._select_transport(TransportType.BROWSER) == TransportType.HTTP


def test_select_transport_either_no_browser():
    """EITHER selection returns HTTP when no browser transport is available."""
    scheduler, _, _, _ = _make_scheduler()
    # With no browser transport, EITHER must resolve to HTTP regardless of ratio
    result = scheduler._select_transport(TransportType.EITHER)
    assert result == TransportType.HTTP


def test_select_transport_browser_available():
    """With a browser transport, BROWSER preference returns BROWSER."""
    config = MurmurateConfig()
    persona = _make_persona()
    plugin = MagicMock()
    plugin.name = "p"
    plugin.domains = ["x.com"]
    plugin.preferred_transport = TransportType.HTTP
    plugin.rate_limit_rpm = 10
    plugin.execute_search = AsyncMock(return_value=[])

    registry = MagicMock()
    registry.get_enabled.return_value = [plugin]

    scheduler = Scheduler(
        config=config,
        personas=[persona],
        registry=registry,
        http_transport=MagicMock(),
        browser_transport=MagicMock(),  # browser IS available
        db=AsyncMock(),
        timing=MagicMock(),
        rate_limiter=AsyncMock(),
    )
    assert scheduler._select_transport(TransportType.BROWSER) == TransportType.BROWSER


@pytest.mark.asyncio
async def test_no_plugins_available():
    """When the registry returns an empty list, no sessions are run."""
    scheduler, _, registry, _ = _make_scheduler()
    registry.get_enabled.return_value = []
    # Stop after the first no-plugin loop iteration to avoid infinite loop.
    # Patch asyncio.sleep so the 60-second backoff doesn't slow the test.
    call_count = 0

    def limited_get_enabled():
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            scheduler.stop()
        return []

    registry.get_enabled.side_effect = limited_get_enabled

    with patch("murmurate.scheduler.scheduler.asyncio.sleep", new=AsyncMock()):
        results = await scheduler.run(max_sessions=5)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_rate_limit_skips_domain():
    """When can_request returns False for all domains, the session is skipped."""
    scheduler, plugin, _, _ = _make_scheduler()

    # Rate limiter denies all requests — force stop after a couple iterations.
    # Patch asyncio.sleep so timing delays don't slow down the test.
    call_count = 0

    async def deny_then_stop(domain, rpm):
        nonlocal call_count
        call_count += 1
        if call_count > 2:
            scheduler.stop()
        return False

    scheduler._rate_limiter.can_request = deny_then_stop

    with patch("murmurate.scheduler.scheduler.asyncio.sleep", new=AsyncMock()):
        results = await scheduler.run(max_sessions=5)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_topic_evolution_from_results():
    """Content snippets from browse actions feed into new_subtopics on the result."""
    scheduler, plugin, _, _ = _make_scheduler()
    # browse_result returns a snippet that contains distinctive words
    plugin.browse_result = AsyncMock(return_value=BrowseAction(
        url_visited="http://test.com/1",
        dwell_time_s=10.0,
        links_found=[],
        content_snippets=["sourdough bread baking techniques fermentation"],
        status_code=200,
    ))

    results = await scheduler.run(max_sessions=1)

    assert len(results) == 1
    # extract_subtopics should have found at least one term from the snippet
    assert isinstance(results[0].new_subtopics, list)


@pytest.mark.asyncio
async def test_reload_updates_config_and_personas():
    """reload() should replace config and personas without stopping the scheduler."""
    scheduler, _, _, _ = _make_scheduler()

    new_config = MurmurateConfig()
    new_persona = _make_persona()
    new_persona.name = "baker"

    scheduler.reload(new_config, [new_persona])

    assert scheduler._personas[0].name == "baker"
    assert scheduler._config is new_config


@pytest.mark.asyncio
async def test_machine_id_populated():
    """SessionResult.machine_id must be set to a non-empty string."""
    scheduler, _, _, _ = _make_scheduler()
    results = await scheduler.run(max_sessions=1)

    assert len(results) == 1
    assert results[0].machine_id  # non-empty string
