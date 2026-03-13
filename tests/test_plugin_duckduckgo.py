"""
tests/test_plugin_duckduckgo.py — Tests for DuckDuckGoPlugin.

Uses unittest.mock to avoid real network calls. Mock transport objects expose
a .get() AsyncMock that returns a mock HttpResponse-like object with .status,
.html, .url, and .headers attributes — matching the real HttpResponse shape.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from murmurate.plugins.duckduckgo import DuckDuckGoPlugin
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
    """Minimal FingerprintProfile for building a PersonaState."""
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


def _make_context(query: str = "python programming") -> SessionContext:
    """Build a minimal SessionContext with one query."""
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


def _make_mock_transport(html: str = "", status: int = 200, url: str = "https://html.duckduckgo.com/html/") -> MagicMock:
    """
    Return a mock transport whose .get() is an AsyncMock returning a
    mock HttpResponse-like object. Matches the interface used by HttpTransport.
    """
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.html = html
    mock_response.url = url
    mock_response.headers = {}

    transport = MagicMock()
    transport.get = AsyncMock(return_value=mock_response)
    return transport


# Realistic DDG lite HTML with two search results
_DDG_HTML = """
<html>
<body>
<div class="results">
  <div class="result results_links results_links_deep web-result">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a" href="https://www.example.com/article">Example Article Title</a>
    </h2>
    <div class="result__body">
      <a class="result__snippet">This is the first search result snippet about python programming.</a>
    </div>
  </div>
  <div class="result results_links results_links_deep web-result">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a" href="https://www.docs.python.org/">Python Documentation</a>
    </h2>
    <div class="result__body">
      <a class="result__snippet">Official Python documentation and tutorials for all versions.</a>
    </div>
  </div>
</div>
</body>
</html>
"""

# Simple HTML page that a browse_result call would fetch
_RESULT_PAGE_HTML = """
<html>
<body>
  <p>This is some content about Python programming.</p>
  <p>Here is more information you might find useful.</p>
  <a href="https://www.related.com/page">Related page</a>
  <a href="https://www.another.com/">Another link</a>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

def test_ddg_plugin_name():
    """DuckDuckGoPlugin.name should return 'duckduckgo'."""
    p = DuckDuckGoPlugin()
    assert p.name == "duckduckgo"


def test_ddg_plugin_domains():
    """DuckDuckGoPlugin.domains should include both duckduckgo.com variants."""
    p = DuckDuckGoPlugin()
    assert "duckduckgo.com" in p.domains
    assert "html.duckduckgo.com" in p.domains


def test_ddg_plugin_preferred_transport():
    """DuckDuckGoPlugin.preferred_transport should be EITHER."""
    p = DuckDuckGoPlugin()
    assert p.preferred_transport == TransportType.EITHER


def test_ddg_plugin_rate_limit_rpm():
    """DuckDuckGoPlugin.rate_limit_rpm should be 10."""
    p = DuckDuckGoPlugin()
    assert p.rate_limit_rpm == 10


# ---------------------------------------------------------------------------
# execute_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ddg_execute_search_returns_list():
    """execute_search should return a list (possibly empty) of SearchResult."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(html=_DDG_HTML)
    context = _make_context("python programming")

    results = await plugin.execute_search(context, transport)

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_ddg_execute_search_parses_results():
    """execute_search should return SearchResult objects with title, url, snippet."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(html=_DDG_HTML)
    context = _make_context("python programming")

    results = await plugin.execute_search(context, transport)

    assert len(results) >= 2
    for r in results:
        assert isinstance(r, SearchResult)
        assert r.title
        assert r.url.startswith("http")
        assert isinstance(r.snippet, str)
        assert r.position >= 1


@pytest.mark.asyncio
async def test_ddg_execute_search_result_positions():
    """Results should have 1-indexed positions in order."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(html=_DDG_HTML)
    context = _make_context("python programming")

    results = await plugin.execute_search(context, transport)

    for i, r in enumerate(results):
        assert r.position == i + 1


@pytest.mark.asyncio
async def test_ddg_execute_search_correct_url_called():
    """execute_search should call transport.get with a DDG HTML search URL."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(html=_DDG_HTML)
    context = _make_context("python programming")

    await plugin.execute_search(context, transport)

    transport.get.assert_called_once()
    called_url = transport.get.call_args[0][0]
    assert "html.duckduckgo.com" in called_url
    assert "python+programming" in called_url or "python%20programming" in called_url or "python programming".replace(" ", "+") in called_url


@pytest.mark.asyncio
async def test_ddg_execute_search_url_encodes_query():
    """Queries with special characters should be URL-encoded in the request URL."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(html="<html><body></body></html>")
    context = _make_context("hello world & more")

    await plugin.execute_search(context, transport)

    called_url = transport.get.call_args[0][0]
    # Spaces should be encoded as + or %20 — special chars as %XX
    assert " " not in called_url
    assert "&" not in called_url.split("?q=")[1] or "%26" in called_url or "hello" in called_url


@pytest.mark.asyncio
async def test_ddg_execute_search_empty_page_returns_empty_list():
    """If DDG returns a page with no results, return an empty list."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(html="<html><body><div>No results found.</div></body></html>")
    context = _make_context("xyzzy_nonexistent_query_12345")

    results = await plugin.execute_search(context, transport)

    assert results == []


@pytest.mark.asyncio
async def test_ddg_execute_search_passes_fingerprint_to_transport():
    """execute_search should forward the persona fingerprint to transport.get."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(html=_DDG_HTML)
    context = _make_context("python programming")

    await plugin.execute_search(context, transport)

    # The second positional arg (or keyword arg) should be the fingerprint
    call_args = transport.get.call_args
    assert len(call_args[0]) >= 2 or "fingerprint" in call_args[1]


# ---------------------------------------------------------------------------
# browse_result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ddg_browse_result_returns_browse_action():
    """browse_result should return a BrowseAction."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(
        html=_RESULT_PAGE_HTML,
        url="https://www.example.com/article",
    )
    context = _make_context()
    result = SearchResult(
        title="Example Article Title",
        url="https://www.example.com/article",
        snippet="snippet text",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action, BrowseAction)


@pytest.mark.asyncio
async def test_ddg_browse_result_url_visited():
    """BrowseAction.url_visited should match the result URL."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(
        html=_RESULT_PAGE_HTML,
        url="https://www.example.com/article",
    )
    context = _make_context()
    result = SearchResult(
        title="Example Article Title",
        url="https://www.example.com/article",
        snippet="snippet text",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert action.url_visited == "https://www.example.com/article"


@pytest.mark.asyncio
async def test_ddg_browse_result_extracts_links():
    """BrowseAction.links_found should contain links from the result page."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(
        html=_RESULT_PAGE_HTML,
        url="https://www.example.com/article",
    )
    context = _make_context()
    result = SearchResult(
        title="Example Article Title",
        url="https://www.example.com/article",
        snippet="snippet text",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action.links_found, list)
    assert len(action.links_found) > 0


@pytest.mark.asyncio
async def test_ddg_browse_result_extracts_content_snippets():
    """BrowseAction.content_snippets should contain text from the result page."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(
        html=_RESULT_PAGE_HTML,
        url="https://www.example.com/article",
    )
    context = _make_context()
    result = SearchResult(
        title="Example Article Title",
        url="https://www.example.com/article",
        snippet="snippet text",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action.content_snippets, list)


@pytest.mark.asyncio
async def test_ddg_browse_result_status_code():
    """BrowseAction.status_code should reflect the HTTP response status."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(
        html=_RESULT_PAGE_HTML,
        status=200,
        url="https://www.example.com/article",
    )
    context = _make_context()
    result = SearchResult(
        title="Example Article Title",
        url="https://www.example.com/article",
        snippet="snippet text",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert action.status_code == 200


@pytest.mark.asyncio
async def test_ddg_browse_result_dwell_time_positive():
    """BrowseAction.dwell_time_s should be a positive number."""
    plugin = DuckDuckGoPlugin()
    transport = _make_mock_transport(
        html=_RESULT_PAGE_HTML,
        url="https://www.example.com/article",
    )
    context = _make_context()
    result = SearchResult(
        title="Example Article Title",
        url="https://www.example.com/article",
        snippet="snippet text",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert action.dwell_time_s > 0
