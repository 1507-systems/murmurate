"""
tests/test_plugin_google.py — Tests for GooglePlugin.

Mock transports return HttpResponse-like objects so no real network calls are
made. The HTML fixtures are minimal but structurally accurate representations
of Google SERP and result page HTML.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from murmurate.plugins.google import GooglePlugin
from murmurate.models import (
    TransportType,
    SessionContext,
    SearchResult,
    BrowseAction,
    PersonaState,
    TopicNode,
    FingerprintProfile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fingerprint() -> FingerprintProfile:
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
        canvas_noise_seed=42,
        fonts=["Arial"],
        created_at="2026-03-12T10:00:00Z",
        last_rotated=None,
    )


def _make_context(query: str = "python tutorial") -> SessionContext:
    persona = PersonaState(
        name="test-persona",
        version=1,
        seeds=["python"],
        topic_tree=[],
        fingerprint=_make_fingerprint(),
        created_at="2026-03-12T10:00:00Z",
        total_sessions=0,
        expertise_level=0.3,
    )
    topic = TopicNode(topic="python", depth=0)
    return SessionContext(
        persona=persona,
        queries=[query],
        current_query_index=0,
        topic_branch=topic,
        expertise_level=0.3,
        prior_results=[],
        session_id="test-session-id",
    )


def _make_mock_transport(html: str = "", status: int = 200, url: str = "https://www.google.com/search") -> MagicMock:
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.html = html
    mock_response.url = url
    mock_response.headers = {}
    transport = MagicMock()
    transport.get = AsyncMock(return_value=mock_response)
    return transport


# Minimal Google SERP HTML with two results using the /url?q= redirect pattern
_GOOGLE_HTML = """
<html>
<body>
<div id="search">
  <div class="g">
    <a href="/url?q=https://www.example.com/article&amp;sa=U">
      <h3>Example Article About Python</h3>
    </a>
  </div>
  <div class="g">
    <a href="/url?q=https://docs.python.org/3/&amp;sa=U">
      <h3>Python 3 Documentation</h3>
    </a>
  </div>
</div>
</body>
</html>
"""

# Simple content page that browse_result would fetch
_RESULT_PAGE_HTML = """
<html>
<body>
  <p>Learn Python programming with these tutorials.</p>
  <p>Python is a versatile language used in data science and web development.</p>
  <a href="https://www.related.com/page">Related tutorial</a>
  <a href="https://www.another.com/">Another resource</a>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

def test_google_plugin_name():
    """GooglePlugin.name should return 'google'."""
    p = GooglePlugin()
    assert p.name == "google"


def test_google_plugin_domains():
    """GooglePlugin.domains should include google.com variants."""
    p = GooglePlugin()
    assert "google.com" in p.domains
    assert "www.google.com" in p.domains


def test_google_plugin_preferred_transport():
    """GooglePlugin.preferred_transport should be EITHER."""
    p = GooglePlugin()
    assert p.preferred_transport == TransportType.EITHER


def test_google_plugin_rate_limit_rpm():
    """GooglePlugin.rate_limit_rpm should be 10."""
    p = GooglePlugin()
    assert p.rate_limit_rpm == 10


# ---------------------------------------------------------------------------
# execute_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_execute_search_returns_list():
    """execute_search should return a list of SearchResult."""
    plugin = GooglePlugin()
    transport = _make_mock_transport(html=_GOOGLE_HTML)
    context = _make_context("python tutorial")

    results = await plugin.execute_search(context, transport)

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_google_execute_search_calls_correct_url():
    """execute_search should call transport.get with a google.com/search URL."""
    plugin = GooglePlugin()
    transport = _make_mock_transport(html=_GOOGLE_HTML)
    context = _make_context("python tutorial")

    await plugin.execute_search(context, transport)

    transport.get.assert_called_once()
    called_url = transport.get.call_args[0][0]
    assert "google.com/search" in called_url
    assert "python" in called_url


@pytest.mark.asyncio
async def test_google_execute_search_url_encodes_query():
    """Spaces and special chars in the query must be URL-encoded."""
    plugin = GooglePlugin()
    transport = _make_mock_transport(html="<html><body></body></html>")
    context = _make_context("machine learning 101")

    await plugin.execute_search(context, transport)

    called_url = transport.get.call_args[0][0]
    assert " " not in called_url


@pytest.mark.asyncio
async def test_google_execute_search_empty_page_returns_empty_list():
    """If Google returns a page with no result links, return empty list."""
    plugin = GooglePlugin()
    transport = _make_mock_transport(html="<html><body><div>No results</div></body></html>")
    context = _make_context("xyzzy_nonexistent_12345")

    results = await plugin.execute_search(context, transport)

    assert results == []


@pytest.mark.asyncio
async def test_google_execute_search_result_positions_are_sequential():
    """Search results should have sequential 1-indexed positions."""
    plugin = GooglePlugin()
    transport = _make_mock_transport(html=_GOOGLE_HTML)
    context = _make_context("python tutorial")

    results = await plugin.execute_search(context, transport)

    # Positions should start at 1 and increase monotonically
    for i, r in enumerate(results):
        assert r.position == i + 1


@pytest.mark.asyncio
async def test_google_execute_search_passes_fingerprint():
    """execute_search should forward the persona fingerprint to transport.get."""
    plugin = GooglePlugin()
    transport = _make_mock_transport(html=_GOOGLE_HTML)
    context = _make_context("python tutorial")

    await plugin.execute_search(context, transport)

    call_args = transport.get.call_args
    assert len(call_args[0]) >= 2 or "fingerprint" in call_args[1]


# ---------------------------------------------------------------------------
# browse_result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_browse_result_returns_browse_action():
    """browse_result should return a BrowseAction."""
    plugin = GooglePlugin()
    transport = _make_mock_transport(html=_RESULT_PAGE_HTML, url="https://www.example.com/article")
    context = _make_context()
    result = SearchResult(
        title="Example Article About Python",
        url="https://www.example.com/article",
        snippet="Learn Python",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action, BrowseAction)


@pytest.mark.asyncio
async def test_google_browse_result_url_visited():
    """BrowseAction.url_visited should match the result URL."""
    plugin = GooglePlugin()
    transport = _make_mock_transport(html=_RESULT_PAGE_HTML, url="https://www.example.com/article")
    context = _make_context()
    result = SearchResult(
        title="Example Article",
        url="https://www.example.com/article",
        snippet="snippet",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert action.url_visited == "https://www.example.com/article"


@pytest.mark.asyncio
async def test_google_browse_result_extracts_links():
    """BrowseAction.links_found should contain links from the result page."""
    plugin = GooglePlugin()
    transport = _make_mock_transport(html=_RESULT_PAGE_HTML, url="https://www.example.com/article")
    context = _make_context()
    result = SearchResult(title="Example", url="https://www.example.com/article", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action.links_found, list)
    assert len(action.links_found) > 0


@pytest.mark.asyncio
async def test_google_browse_result_dwell_time_positive():
    """BrowseAction.dwell_time_s should be a positive number."""
    plugin = GooglePlugin()
    transport = _make_mock_transport(html=_RESULT_PAGE_HTML, url="https://www.example.com/article")
    context = _make_context()
    result = SearchResult(title="Example", url="https://www.example.com/article", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert action.dwell_time_s > 0


@pytest.mark.asyncio
async def test_google_browse_result_status_code():
    """BrowseAction.status_code should reflect the HTTP response status."""
    plugin = GooglePlugin()
    transport = _make_mock_transport(html=_RESULT_PAGE_HTML, status=200, url="https://www.example.com/article")
    context = _make_context()
    result = SearchResult(title="Example", url="https://www.example.com/article", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert action.status_code == 200
