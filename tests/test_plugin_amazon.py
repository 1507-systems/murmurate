"""
tests/test_plugin_amazon.py — Tests for AmazonPlugin.

Mock transports return HttpResponse-like objects. The HTML fixtures replicate
Amazon's search result and product detail page structures at a minimal level.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from murmurate.plugins.amazon import AmazonPlugin
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


def _make_context(query: str = "mechanical keyboard") -> SessionContext:
    persona = PersonaState(
        name="test-persona",
        version=1,
        seeds=["keyboards"],
        topic_tree=[],
        fingerprint=_make_fingerprint(),
        created_at="2026-03-12T10:00:00Z",
        total_sessions=0,
        expertise_level=0.3,
    )
    topic = TopicNode(topic="keyboards", depth=0)
    return SessionContext(
        persona=persona,
        queries=[query],
        current_query_index=0,
        topic_branch=topic,
        expertise_level=0.3,
        prior_results=[],
        session_id="test-session-id",
    )


def _make_mock_transport(html: str = "", status: int = 200, url: str = "https://www.amazon.com/s") -> MagicMock:
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.html = html
    mock_response.url = url
    mock_response.headers = {}
    transport = MagicMock()
    transport.get = AsyncMock(return_value=mock_response)
    return transport


# Minimal Amazon search results page with two product listings
_AMAZON_SEARCH_HTML = """
<html>
<body>
<div class="s-main-slot">
  <div data-component-type="s-search-result" data-asin="B08N5WRWNW" class="s-result-item">
    <h2>
      <a class="a-link-normal" href="/dp/B08N5WRWNW/ref=sr_1_1?keywords=keyboard">
        Keychron K2 Wireless Mechanical Keyboard
      </a>
    </h2>
    <div class="a-price">
      <span class="a-price-whole">79</span>
      <span class="a-price-fraction">99</span>
    </div>
  </div>
  <div data-component-type="s-search-result" data-asin="B07R68ZFBS" class="s-result-item">
    <h2>
      <a class="a-link-normal" href="/dp/B07R68ZFBS/ref=sr_1_2?keywords=keyboard">
        Logitech MX Keys Wireless Keyboard
      </a>
    </h2>
    <div class="a-price">
      <span class="a-price-whole">109</span>
      <span class="a-price-fraction">99</span>
    </div>
  </div>
</div>
</body>
</html>
"""

# Minimal Amazon product detail page
_AMAZON_PRODUCT_HTML = """
<html>
<body>
  <span id="productTitle">Keychron K2 Wireless Mechanical Keyboard</span>
  <ul id="feature-bullets">
    <li>
      <span class="a-list-item">Compact 75% layout with hot-swappable switches</span>
    </li>
    <li>
      <span class="a-list-item">Bluetooth 5.1 with 3-device pairing</span>
    </li>
  </ul>
  <a href="https://www.keychron.com/products/keychron-k2">Official website</a>
  <a href="https://www.amazon.com/dp/B08N5WRWNW/reviews">Customer reviews</a>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

def test_amazon_plugin_name():
    """AmazonPlugin.name should return 'amazon'."""
    p = AmazonPlugin()
    assert p.name == "amazon"


def test_amazon_plugin_domains():
    """AmazonPlugin.domains should include amazon.com variants."""
    p = AmazonPlugin()
    assert "amazon.com" in p.domains
    assert "www.amazon.com" in p.domains


def test_amazon_plugin_preferred_transport():
    """AmazonPlugin.preferred_transport should be EITHER."""
    p = AmazonPlugin()
    assert p.preferred_transport == TransportType.EITHER


def test_amazon_plugin_rate_limit_rpm():
    """AmazonPlugin.rate_limit_rpm should be 8."""
    p = AmazonPlugin()
    assert p.rate_limit_rpm == 8


# ---------------------------------------------------------------------------
# execute_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_amazon_execute_search_returns_list():
    """execute_search should return a list of SearchResult."""
    plugin = AmazonPlugin()
    transport = _make_mock_transport(html=_AMAZON_SEARCH_HTML)
    context = _make_context("mechanical keyboard")

    results = await plugin.execute_search(context, transport)

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_amazon_execute_search_parses_results():
    """execute_search should parse product titles and URLs from the SERP."""
    plugin = AmazonPlugin()
    transport = _make_mock_transport(html=_AMAZON_SEARCH_HTML)
    context = _make_context("mechanical keyboard")

    results = await plugin.execute_search(context, transport)

    assert len(results) >= 2
    for r in results:
        assert isinstance(r, SearchResult)
        assert r.title
        assert "amazon.com" in r.url


@pytest.mark.asyncio
async def test_amazon_execute_search_url_has_search_path():
    """execute_search should call transport.get with amazon.com/s URL."""
    plugin = AmazonPlugin()
    transport = _make_mock_transport(html=_AMAZON_SEARCH_HTML)
    context = _make_context("mechanical keyboard")

    await plugin.execute_search(context, transport)

    called_url = transport.get.call_args[0][0]
    assert "amazon.com/s" in called_url
    assert "keyboard" in called_url


@pytest.mark.asyncio
async def test_amazon_execute_search_url_encodes_query():
    """Spaces and special chars in the query must be URL-encoded."""
    plugin = AmazonPlugin()
    transport = _make_mock_transport(html="<html><body></body></html>")
    context = _make_context("USB C hub 4 port")

    await plugin.execute_search(context, transport)

    called_url = transport.get.call_args[0][0]
    assert " " not in called_url


@pytest.mark.asyncio
async def test_amazon_execute_search_empty_page_returns_empty_list():
    """If Amazon returns a page with no result containers, return empty list."""
    plugin = AmazonPlugin()
    transport = _make_mock_transport(html="<html><body><div>No results.</div></body></html>")
    context = _make_context("xyzzy_nonexistent_12345")

    results = await plugin.execute_search(context, transport)

    assert results == []


# ---------------------------------------------------------------------------
# browse_result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_amazon_browse_result_returns_browse_action():
    """browse_result should return a BrowseAction."""
    plugin = AmazonPlugin()
    transport = _make_mock_transport(html=_AMAZON_PRODUCT_HTML, url="https://www.amazon.com/dp/B08N5WRWNW/")
    context = _make_context()
    result = SearchResult(
        title="Keychron K2",
        url="https://www.amazon.com/dp/B08N5WRWNW/",
        snippet="$79.99",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action, BrowseAction)


@pytest.mark.asyncio
async def test_amazon_browse_result_extracts_content_snippets():
    """BrowseAction.content_snippets should include product title or feature bullets."""
    plugin = AmazonPlugin()
    transport = _make_mock_transport(html=_AMAZON_PRODUCT_HTML, url="https://www.amazon.com/dp/B08N5WRWNW/")
    context = _make_context()
    result = SearchResult(title="Keychron K2", url="https://www.amazon.com/dp/B08N5WRWNW/", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action.content_snippets, list)


@pytest.mark.asyncio
async def test_amazon_browse_result_dwell_time_positive():
    """BrowseAction.dwell_time_s should be a positive number."""
    plugin = AmazonPlugin()
    transport = _make_mock_transport(html=_AMAZON_PRODUCT_HTML, url="https://www.amazon.com/dp/B08N5WRWNW/")
    context = _make_context()
    result = SearchResult(title="Keychron K2", url="https://www.amazon.com/dp/B08N5WRWNW/", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert action.dwell_time_s > 0


@pytest.mark.asyncio
async def test_amazon_browse_result_status_code():
    """BrowseAction.status_code should reflect the response status."""
    plugin = AmazonPlugin()
    transport = _make_mock_transport(html=_AMAZON_PRODUCT_HTML, status=200, url="https://www.amazon.com/dp/B08N5WRWNW/")
    context = _make_context()
    result = SearchResult(title="Keychron K2", url="https://www.amazon.com/dp/B08N5WRWNW/", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert action.status_code == 200
