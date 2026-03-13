"""
tests/test_plugin_bing.py — Tests for BingPlugin.

HTML fixtures use Bing's <li class="b_algo"> result structure. Mock transports
return HttpResponse-like objects without making real network calls.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from murmurate.plugins.bing import BingPlugin
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


def _make_context(query: str = "python web scraping") -> SessionContext:
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


def _make_mock_transport(html: str = "", status: int = 200, url: str = "https://www.bing.com/search") -> MagicMock:
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.html = html
    mock_response.url = url
    mock_response.headers = {}
    transport = MagicMock()
    transport.get = AsyncMock(return_value=mock_response)
    return transport


# Minimal Bing SERP HTML using the b_algo structure
_BING_HTML = """
<html>
<body>
<ol id="b_results">
  <li class="b_algo">
    <h2>
      <a href="https://realpython.com/beautiful-soup-web-scraper-python/">
        Beautiful Soup: Build a Web Scraper With Python
      </a>
    </h2>
    <div class="b_caption">
      <p>Learn how to use Beautiful Soup for Python web scraping in this step-by-step tutorial.</p>
    </div>
  </li>
  <li class="b_algo">
    <h2>
      <a href="https://docs.python-requests.org/">
        Requests: HTTP for Humans
      </a>
    </h2>
    <div class="b_caption">
      <p>Requests is the most popular Python HTTP library for making web requests.</p>
    </div>
  </li>
</ol>
</body>
</html>
"""

# Simple content page that browse_result would fetch
_RESULT_PAGE_HTML = """
<html>
<body>
  <p>Python web scraping with Beautiful Soup is straightforward and powerful.</p>
  <p>You can extract data from any website using these techniques.</p>
  <a href="https://www.crummy.com/software/BeautifulSoup/">BeautifulSoup docs</a>
  <a href="https://scrapy.org/">Scrapy framework</a>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

def test_bing_plugin_name():
    """BingPlugin.name should return 'bing'."""
    p = BingPlugin()
    assert p.name == "bing"


def test_bing_plugin_domains():
    """BingPlugin.domains should include bing.com variants."""
    p = BingPlugin()
    assert "bing.com" in p.domains
    assert "www.bing.com" in p.domains


def test_bing_plugin_preferred_transport():
    """BingPlugin.preferred_transport should be EITHER."""
    p = BingPlugin()
    assert p.preferred_transport == TransportType.EITHER


def test_bing_plugin_rate_limit_rpm():
    """BingPlugin.rate_limit_rpm should be 12."""
    p = BingPlugin()
    assert p.rate_limit_rpm == 12


# ---------------------------------------------------------------------------
# execute_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bing_execute_search_returns_list():
    """execute_search should return a list of SearchResult."""
    plugin = BingPlugin()
    transport = _make_mock_transport(html=_BING_HTML)
    context = _make_context("python web scraping")

    results = await plugin.execute_search(context, transport)

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_bing_execute_search_parses_results():
    """execute_search should extract titles, URLs, and snippets from b_algo elements."""
    plugin = BingPlugin()
    transport = _make_mock_transport(html=_BING_HTML)
    context = _make_context("python web scraping")

    results = await plugin.execute_search(context, transport)

    assert len(results) >= 2
    for r in results:
        assert isinstance(r, SearchResult)
        assert r.title
        assert r.url.startswith("http")
        assert isinstance(r.snippet, str)
        assert r.position >= 1


@pytest.mark.asyncio
async def test_bing_execute_search_calls_correct_url():
    """execute_search should call transport.get with a bing.com/search URL."""
    plugin = BingPlugin()
    transport = _make_mock_transport(html=_BING_HTML)
    context = _make_context("python web scraping")

    await plugin.execute_search(context, transport)

    transport.get.assert_called_once()
    called_url = transport.get.call_args[0][0]
    assert "bing.com/search" in called_url
    assert "python" in called_url


@pytest.mark.asyncio
async def test_bing_execute_search_url_encodes_query():
    """Spaces and special chars in the query must be URL-encoded."""
    plugin = BingPlugin()
    transport = _make_mock_transport(html="<html><body></body></html>")
    context = _make_context("C++ template metaprogramming")

    await plugin.execute_search(context, transport)

    called_url = transport.get.call_args[0][0]
    assert " " not in called_url


@pytest.mark.asyncio
async def test_bing_execute_search_empty_page_returns_empty_list():
    """If Bing returns a page with no b_algo elements, return empty list."""
    plugin = BingPlugin()
    transport = _make_mock_transport(html="<html><body><div>No results found.</div></body></html>")
    context = _make_context("xyzzy_nonexistent_12345")

    results = await plugin.execute_search(context, transport)

    assert results == []


@pytest.mark.asyncio
async def test_bing_execute_search_result_positions():
    """Results should have sequential 1-indexed positions."""
    plugin = BingPlugin()
    transport = _make_mock_transport(html=_BING_HTML)
    context = _make_context("python web scraping")

    results = await plugin.execute_search(context, transport)

    for i, r in enumerate(results):
        assert r.position == i + 1


# ---------------------------------------------------------------------------
# browse_result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bing_browse_result_returns_browse_action():
    """browse_result should return a BrowseAction."""
    plugin = BingPlugin()
    transport = _make_mock_transport(html=_RESULT_PAGE_HTML, url="https://realpython.com/beautiful-soup-web-scraper-python/")
    context = _make_context()
    result = SearchResult(
        title="Beautiful Soup: Build a Web Scraper With Python",
        url="https://realpython.com/beautiful-soup-web-scraper-python/",
        snippet="Learn how to use Beautiful Soup",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action, BrowseAction)


@pytest.mark.asyncio
async def test_bing_browse_result_url_visited():
    """BrowseAction.url_visited should match the result URL."""
    plugin = BingPlugin()
    transport = _make_mock_transport(html=_RESULT_PAGE_HTML, url="https://realpython.com/article/")
    context = _make_context()
    result = SearchResult(title="Article", url="https://realpython.com/article/", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert action.url_visited == "https://realpython.com/article/"


@pytest.mark.asyncio
async def test_bing_browse_result_extracts_links():
    """BrowseAction.links_found should contain links from the result page."""
    plugin = BingPlugin()
    transport = _make_mock_transport(html=_RESULT_PAGE_HTML, url="https://realpython.com/article/")
    context = _make_context()
    result = SearchResult(title="Article", url="https://realpython.com/article/", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action.links_found, list)
    assert len(action.links_found) > 0


@pytest.mark.asyncio
async def test_bing_browse_result_dwell_time_positive():
    """BrowseAction.dwell_time_s should be a positive number."""
    plugin = BingPlugin()
    transport = _make_mock_transport(html=_RESULT_PAGE_HTML, url="https://realpython.com/article/")
    context = _make_context()
    result = SearchResult(title="Article", url="https://realpython.com/article/", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert action.dwell_time_s > 0


@pytest.mark.asyncio
async def test_bing_browse_result_status_code():
    """BrowseAction.status_code should reflect the HTTP response status."""
    plugin = BingPlugin()
    transport = _make_mock_transport(html=_RESULT_PAGE_HTML, status=200, url="https://realpython.com/article/")
    context = _make_context()
    result = SearchResult(title="Article", url="https://realpython.com/article/", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert action.status_code == 200
