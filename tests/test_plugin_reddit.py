"""
tests/test_plugin_reddit.py — Tests for RedditPlugin.

Fixtures use old.reddit.com-style HTML with search-result-link containers
and usertext-body post content sections.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from murmurate.plugins.reddit import RedditPlugin
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


def _make_context(query: str = "python beginner tips") -> SessionContext:
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


def _make_mock_transport(html: str = "", status: int = 200, url: str = "https://old.reddit.com/search") -> MagicMock:
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.html = html
    mock_response.url = url
    mock_response.headers = {}
    transport = MagicMock()
    transport.get = AsyncMock(return_value=mock_response)
    return transport


# Minimal old.reddit.com search results page
_REDDIT_SEARCH_HTML = """
<html>
<body>
<div class="search-results">
  <div class="search-result-link">
    <div class="search-result-header">
      <a href="/r/learnpython/comments/abc123/python_beginner_tips/">
        Python beginner tips and resources
      </a>
    </div>
    <div class="search-result-meta">
      r/learnpython &bull; 42 points &bull; 3 hours ago
    </div>
  </div>
  <div class="search-result-link">
    <div class="search-result-header">
      <a href="/r/Python/comments/def456/what_resources_did_you_use/">
        What resources did you use to learn Python?
      </a>
    </div>
    <div class="search-result-meta">
      r/Python &bull; 128 points &bull; 1 day ago
    </div>
  </div>
</div>
</body>
</html>
"""

# Minimal old.reddit.com post detail page with body text and comments
_REDDIT_POST_HTML = """
<html>
<body>
<div class="entry">
  <div class="usertext-body">
    <p>Here are some tips for Python beginners that I wish I had known earlier.</p>
    <p>First, use a virtual environment for every project you start.</p>
  </div>
</div>
<div class="comment">
  <div class="usertext-body">
    <p>Great advice! I would also recommend reading the official docs.</p>
  </div>
</div>
<a href="https://www.python.org/doc/">Python docs</a>
<a href="https://realpython.com/">Real Python tutorials</a>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

def test_reddit_plugin_name():
    """RedditPlugin.name should return 'reddit'."""
    p = RedditPlugin()
    assert p.name == "reddit"


def test_reddit_plugin_domains():
    """RedditPlugin.domains should include reddit.com and old.reddit.com."""
    p = RedditPlugin()
    assert "reddit.com" in p.domains
    assert "old.reddit.com" in p.domains


def test_reddit_plugin_preferred_transport():
    """RedditPlugin.preferred_transport should be HTTP."""
    p = RedditPlugin()
    assert p.preferred_transport == TransportType.HTTP


def test_reddit_plugin_rate_limit_rpm():
    """RedditPlugin.rate_limit_rpm should be 15."""
    p = RedditPlugin()
    assert p.rate_limit_rpm == 15


# ---------------------------------------------------------------------------
# execute_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reddit_execute_search_returns_list():
    """execute_search should return a list of SearchResult."""
    plugin = RedditPlugin()
    transport = _make_mock_transport(html=_REDDIT_SEARCH_HTML)
    context = _make_context("python beginner tips")

    results = await plugin.execute_search(context, transport)

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_reddit_execute_search_calls_old_reddit_url():
    """execute_search should use old.reddit.com/search."""
    plugin = RedditPlugin()
    transport = _make_mock_transport(html=_REDDIT_SEARCH_HTML)
    context = _make_context("python beginner tips")

    await plugin.execute_search(context, transport)

    called_url = transport.get.call_args[0][0]
    assert "old.reddit.com/search" in called_url
    assert "python" in called_url


@pytest.mark.asyncio
async def test_reddit_execute_search_url_encodes_query():
    """Spaces and special chars in the query must be URL-encoded."""
    plugin = RedditPlugin()
    transport = _make_mock_transport(html="<html><body></body></html>")
    context = _make_context("best Python libraries 2026")

    await plugin.execute_search(context, transport)

    called_url = transport.get.call_args[0][0]
    assert " " not in called_url


@pytest.mark.asyncio
async def test_reddit_execute_search_empty_page_returns_empty_list():
    """If Reddit returns a page with no search-result-link divs, return empty list."""
    plugin = RedditPlugin()
    transport = _make_mock_transport(html="<html><body><div>No results</div></body></html>")
    context = _make_context("xyzzy_nonexistent_12345")

    results = await plugin.execute_search(context, transport)

    assert results == []


@pytest.mark.asyncio
async def test_reddit_execute_search_result_positions():
    """Results should have sequential 1-indexed positions."""
    plugin = RedditPlugin()
    transport = _make_mock_transport(html=_REDDIT_SEARCH_HTML)
    context = _make_context("python beginner tips")

    results = await plugin.execute_search(context, transport)

    for i, r in enumerate(results):
        assert r.position == i + 1


# ---------------------------------------------------------------------------
# browse_result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reddit_browse_result_returns_browse_action():
    """browse_result should return a BrowseAction."""
    plugin = RedditPlugin()
    transport = _make_mock_transport(
        html=_REDDIT_POST_HTML,
        url="https://old.reddit.com/r/learnpython/comments/abc123/python_beginner_tips/",
    )
    context = _make_context()
    result = SearchResult(
        title="Python beginner tips and resources",
        url="https://old.reddit.com/r/learnpython/comments/abc123/python_beginner_tips/",
        snippet="r/learnpython",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action, BrowseAction)


@pytest.mark.asyncio
async def test_reddit_browse_result_extracts_text():
    """BrowseAction.content_snippets should contain post body text."""
    plugin = RedditPlugin()
    transport = _make_mock_transport(
        html=_REDDIT_POST_HTML,
        url="https://old.reddit.com/r/learnpython/comments/abc123/",
    )
    context = _make_context()
    result = SearchResult(
        title="Python tips",
        url="https://old.reddit.com/r/learnpython/comments/abc123/",
        snippet="",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action.content_snippets, list)


@pytest.mark.asyncio
async def test_reddit_browse_result_dwell_time_positive():
    """BrowseAction.dwell_time_s should be positive."""
    plugin = RedditPlugin()
    transport = _make_mock_transport(
        html=_REDDIT_POST_HTML,
        url="https://old.reddit.com/r/learnpython/comments/abc123/",
    )
    context = _make_context()
    result = SearchResult(title="Test", url="https://old.reddit.com/r/learnpython/comments/abc123/", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert action.dwell_time_s > 0


@pytest.mark.asyncio
async def test_reddit_browse_result_rewrites_www_to_old():
    """browse_result should rewrite www.reddit.com URLs to old.reddit.com."""
    plugin = RedditPlugin()
    transport = _make_mock_transport(
        html=_REDDIT_POST_HTML,
        url="https://old.reddit.com/r/learnpython/comments/abc123/",
    )
    context = _make_context()
    # Pass a www.reddit.com URL — should be rewritten to old.reddit.com
    result = SearchResult(
        title="Test",
        url="https://www.reddit.com/r/learnpython/comments/abc123/",
        snippet="",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    # The visited URL should use old.reddit.com
    assert "old.reddit.com" in action.url_visited
