"""
tests/test_plugin_wikipedia.py — Tests for WikipediaPlugin.

Uses unittest.mock to avoid real network calls. Mock transport objects expose
a .get() AsyncMock returning a mock HttpResponse-like object with .status,
.html, .url, and .headers attributes — matching the real HttpResponse shape.

Wikipedia's opensearch API returns JSON as a four-element array:
  [query_string, [titles], [descriptions], [urls]]
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from murmurate.plugins.wikipedia import WikipediaPlugin
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


def _make_context(query: str = "python programming language") -> SessionContext:
    """Build a minimal SessionContext with one query."""
    persona = PersonaState(
        name="wiki-persona",
        version=1,
        seeds=["python"],
        topic_tree=[],
        fingerprint=_make_fingerprint(),
        created_at="2026-03-12T10:00:00Z",
        total_sessions=0,
        expertise_level=0.5,
    )
    topic = TopicNode(topic="python", depth=0)
    return SessionContext(
        persona=persona,
        queries=[query],
        current_query_index=0,
        topic_branch=topic,
        expertise_level=0.5,
        prior_results=[],
        session_id="wiki-session-id",
    )


def _make_mock_transport(html: str = "", status: int = 200, url: str = "https://en.wikipedia.org/") -> MagicMock:
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


# Realistic Wikipedia opensearch JSON response
_OPENSEARCH_JSON = json.dumps([
    "python programming language",
    ["Python (programming language)", "Python (genus)", "Python software"],
    [
        "Python is a high-level, general-purpose programming language.",
        "Python is a genus of constricting snakes.",
        "Python is open-source software.",
    ],
    [
        "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "https://en.wikipedia.org/wiki/Python_(genus)",
        "https://en.wikipedia.org/wiki/Python_software",
    ],
])

# Realistic Wikipedia article HTML (simplified)
_ARTICLE_HTML = """
<html>
<head><title>Python (programming language) - Wikipedia</title></head>
<body>
<div id="mw-content-text">
  <p>Python is a high-level, general-purpose programming language. Its design philosophy emphasizes code readability.</p>
  <p>Guido van Rossum began working on Python in the late 1980s as a successor to the ABC programming language.</p>
  <p>Python consistently ranks as one of the most popular programming languages.</p>
  <a href="/wiki/Guido_van_Rossum">Guido van Rossum</a>
  <a href="/wiki/ABC_programming_language">ABC programming language</a>
  <a href="https://www.python.org/">Official Python website</a>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

def test_wiki_plugin_name():
    """WikipediaPlugin.name should return 'wikipedia'."""
    p = WikipediaPlugin()
    assert p.name == "wikipedia"


def test_wiki_plugin_domains():
    """WikipediaPlugin.domains should include en.wikipedia.org."""
    p = WikipediaPlugin()
    assert "en.wikipedia.org" in p.domains


def test_wiki_plugin_preferred_transport():
    """WikipediaPlugin.preferred_transport should be HTTP."""
    p = WikipediaPlugin()
    assert p.preferred_transport == TransportType.HTTP


def test_wiki_plugin_rate_limit_rpm():
    """WikipediaPlugin.rate_limit_rpm should be 30."""
    p = WikipediaPlugin()
    assert p.rate_limit_rpm == 30


# ---------------------------------------------------------------------------
# execute_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wiki_execute_search_returns_list():
    """execute_search should return a list of SearchResult."""
    plugin = WikipediaPlugin()
    transport = _make_mock_transport(html=_OPENSEARCH_JSON)
    context = _make_context("python programming language")

    results = await plugin.execute_search(context, transport)

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_wiki_execute_search_parses_results():
    """execute_search should return SearchResult objects parsed from opensearch JSON."""
    plugin = WikipediaPlugin()
    transport = _make_mock_transport(html=_OPENSEARCH_JSON)
    context = _make_context("python programming language")

    results = await plugin.execute_search(context, transport)

    assert len(results) == 3
    for r in results:
        assert isinstance(r, SearchResult)
        assert r.title
        assert r.url.startswith("https://en.wikipedia.org/")
        assert isinstance(r.snippet, str)
        assert r.position >= 1


@pytest.mark.asyncio
async def test_wiki_execute_search_result_positions():
    """Results should have 1-indexed positions in order."""
    plugin = WikipediaPlugin()
    transport = _make_mock_transport(html=_OPENSEARCH_JSON)
    context = _make_context("python programming language")

    results = await plugin.execute_search(context, transport)

    for i, r in enumerate(results):
        assert r.position == i + 1


@pytest.mark.asyncio
async def test_wiki_execute_search_correct_url_called():
    """execute_search should call transport.get with the Wikipedia opensearch API URL."""
    plugin = WikipediaPlugin()
    transport = _make_mock_transport(html=_OPENSEARCH_JSON)
    context = _make_context("python programming language")

    await plugin.execute_search(context, transport)

    transport.get.assert_called_once()
    called_url = transport.get.call_args[0][0]
    assert "en.wikipedia.org" in called_url
    assert "opensearch" in called_url
    assert "python" in called_url.lower()


@pytest.mark.asyncio
async def test_wiki_execute_search_url_encodes_query():
    """Queries with spaces should be URL-encoded in the opensearch request URL."""
    plugin = WikipediaPlugin()
    transport = _make_mock_transport(html=json.dumps(["q", [], [], []]))
    context = _make_context("hello world")

    await plugin.execute_search(context, transport)

    called_url = transport.get.call_args[0][0]
    assert " " not in called_url


@pytest.mark.asyncio
async def test_wiki_execute_search_empty_response_returns_empty_list():
    """If opensearch returns zero results, return an empty list."""
    plugin = WikipediaPlugin()
    empty_json = json.dumps(["no results", [], [], []])
    transport = _make_mock_transport(html=empty_json)
    context = _make_context("xyzzy_nonexistent_12345")

    results = await plugin.execute_search(context, transport)

    assert results == []


@pytest.mark.asyncio
async def test_wiki_execute_search_passes_fingerprint_to_transport():
    """execute_search should forward the persona fingerprint to transport.get."""
    plugin = WikipediaPlugin()
    transport = _make_mock_transport(html=_OPENSEARCH_JSON)
    context = _make_context()

    await plugin.execute_search(context, transport)

    call_args = transport.get.call_args
    assert len(call_args[0]) >= 2 or "fingerprint" in call_args[1]


# ---------------------------------------------------------------------------
# browse_result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wiki_browse_result_returns_browse_action():
    """browse_result should return a BrowseAction."""
    plugin = WikipediaPlugin()
    transport = _make_mock_transport(
        html=_ARTICLE_HTML,
        url="https://en.wikipedia.org/wiki/Python_(programming_language)",
    )
    context = _make_context()
    result = SearchResult(
        title="Python (programming language)",
        url="https://en.wikipedia.org/wiki/Python_(programming_language)",
        snippet="Python is a high-level, general-purpose programming language.",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action, BrowseAction)


@pytest.mark.asyncio
async def test_wiki_browse_result_url_visited():
    """BrowseAction.url_visited should match the result URL."""
    plugin = WikipediaPlugin()
    article_url = "https://en.wikipedia.org/wiki/Python_(programming_language)"
    transport = _make_mock_transport(
        html=_ARTICLE_HTML,
        url=article_url,
    )
    context = _make_context()
    result = SearchResult(
        title="Python (programming language)",
        url=article_url,
        snippet="Python is a high-level, general-purpose programming language.",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert action.url_visited == article_url


@pytest.mark.asyncio
async def test_wiki_browse_result_extracts_links():
    """BrowseAction.links_found should contain links from the article."""
    plugin = WikipediaPlugin()
    transport = _make_mock_transport(
        html=_ARTICLE_HTML,
        url="https://en.wikipedia.org/wiki/Python_(programming_language)",
    )
    context = _make_context()
    result = SearchResult(
        title="Python (programming language)",
        url="https://en.wikipedia.org/wiki/Python_(programming_language)",
        snippet="snippet",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action.links_found, list)
    assert len(action.links_found) > 0


@pytest.mark.asyncio
async def test_wiki_browse_result_extracts_content_snippets():
    """BrowseAction.content_snippets should contain paragraph text from the article."""
    plugin = WikipediaPlugin()
    transport = _make_mock_transport(
        html=_ARTICLE_HTML,
        url="https://en.wikipedia.org/wiki/Python_(programming_language)",
    )
    context = _make_context()
    result = SearchResult(
        title="Python (programming language)",
        url="https://en.wikipedia.org/wiki/Python_(programming_language)",
        snippet="snippet",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action.content_snippets, list)
    assert len(action.content_snippets) > 0


@pytest.mark.asyncio
async def test_wiki_browse_result_status_code():
    """BrowseAction.status_code should match the HTTP response status."""
    plugin = WikipediaPlugin()
    transport = _make_mock_transport(
        html=_ARTICLE_HTML,
        status=200,
        url="https://en.wikipedia.org/wiki/Python_(programming_language)",
    )
    context = _make_context()
    result = SearchResult(
        title="Python (programming language)",
        url="https://en.wikipedia.org/wiki/Python_(programming_language)",
        snippet="snippet",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert action.status_code == 200


@pytest.mark.asyncio
async def test_wiki_browse_result_dwell_time_positive():
    """BrowseAction.dwell_time_s should be a positive number."""
    plugin = WikipediaPlugin()
    transport = _make_mock_transport(
        html=_ARTICLE_HTML,
        url="https://en.wikipedia.org/wiki/Python_(programming_language)",
    )
    context = _make_context()
    result = SearchResult(
        title="Python (programming language)",
        url="https://en.wikipedia.org/wiki/Python_(programming_language)",
        snippet="snippet",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert action.dwell_time_s > 0
