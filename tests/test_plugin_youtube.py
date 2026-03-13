"""
tests/test_plugin_youtube.py — Tests for YouTubePlugin.

Mock transports cover both the .get() (HTTP) and .navigate() (browser) paths.
The HTML fixtures include a minimal ytInitialData JSON blob to exercise the
primary extraction path, plus a fallback anchor-href-only page.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from murmurate.plugins.youtube import YouTubePlugin
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


def _make_http_transport(html: str = "", status: int = 200, url: str = "https://www.youtube.com/results") -> MagicMock:
    """HTTP transport mock with only .get()."""
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.html = html
    mock_response.url = url
    mock_response.headers = {}
    transport = MagicMock(spec=["get"])
    transport.get = AsyncMock(return_value=mock_response)
    return transport


def _make_browser_transport(html: str = "", status: int = 200, url: str = "https://www.youtube.com/results") -> MagicMock:
    """Browser transport mock with .navigate() instead of .get()."""
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.html = html
    mock_response.url = url
    mock_response.headers = {}
    transport = MagicMock(spec=["navigate"])
    transport.navigate = AsyncMock(return_value=mock_response)
    return transport


# Minimal ytInitialData blob embedded in a script tag
_INITIAL_DATA = {
    "contents": {
        "twoColumnSearchResultsRenderer": {
            "primaryContents": {
                "sectionListRenderer": {
                    "contents": [
                        {
                            "itemSectionRenderer": {
                                "contents": [
                                    {
                                        "videoRenderer": {
                                            "videoId": "dQw4w9WgXcQ",
                                            "title": {
                                                "runs": [{"text": "Never Gonna Give You Up"}]
                                            },
                                            "descriptionSnippet": {
                                                "runs": [{"text": "Official music video"}]
                                            },
                                        }
                                    },
                                    {
                                        "videoRenderer": {
                                            "videoId": "abc123defgh",
                                            "title": {
                                                "runs": [{"text": "Python Tutorial for Beginners"}]
                                            },
                                            "descriptionSnippet": {
                                                "runs": [{"text": "Learn Python in 2 hours"}]
                                            },
                                        }
                                    },
                                ]
                            }
                        }
                    ]
                }
            }
        }
    }
}

_YOUTUBE_HTML = f"""<html>
<head><script>var ytInitialData = {json.dumps(_INITIAL_DATA)};</script></head>
<body>
<a href="/watch?v=dQw4w9WgXcQ">Never Gonna Give You Up</a>
<a href="/watch?v=abc123defgh">Python Tutorial</a>
</body>
</html>"""

# Fallback HTML without ytInitialData (plain anchor links only)
_FALLBACK_HTML = """<html>
<body>
<a href="/watch?v=xyz789abcde">Some Video Title</a>
<a href="/watch?v=aaaabbbbccc">Another Video</a>
</body>
</html>"""

_WATCH_PAGE_HTML = """
<html>
<body>
  <p>This is a great video about Python.</p>
  <a href="https://www.example.com/related">Related content</a>
  <a href="https://www.youtube.com/watch?v=other123vid">Related video</a>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

def test_youtube_plugin_name():
    """YouTubePlugin.name should return 'youtube'."""
    p = YouTubePlugin()
    assert p.name == "youtube"


def test_youtube_plugin_domains():
    """YouTubePlugin.domains should include youtube.com variants."""
    p = YouTubePlugin()
    assert "youtube.com" in p.domains
    assert "www.youtube.com" in p.domains


def test_youtube_plugin_preferred_transport():
    """YouTubePlugin.preferred_transport should be BROWSER."""
    p = YouTubePlugin()
    assert p.preferred_transport == TransportType.BROWSER


def test_youtube_plugin_rate_limit_rpm():
    """YouTubePlugin.rate_limit_rpm should be 5."""
    p = YouTubePlugin()
    assert p.rate_limit_rpm == 5


# ---------------------------------------------------------------------------
# execute_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_youtube_execute_search_returns_list_http():
    """execute_search via HTTP transport should return a list."""
    plugin = YouTubePlugin()
    transport = _make_http_transport(html=_YOUTUBE_HTML)
    context = _make_context("python tutorial")

    results = await plugin.execute_search(context, transport)

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_youtube_execute_search_parses_initial_data():
    """execute_search should extract videos from ytInitialData when present."""
    plugin = YouTubePlugin()
    transport = _make_http_transport(html=_YOUTUBE_HTML)
    context = _make_context("python tutorial")

    results = await plugin.execute_search(context, transport)

    assert len(results) >= 2
    urls = [r.url for r in results]
    assert any("dQw4w9WgXcQ" in u for u in urls)


@pytest.mark.asyncio
async def test_youtube_execute_search_fallback_to_anchor_links():
    """execute_search should fall back to scanning /watch?v= links if no ytInitialData."""
    plugin = YouTubePlugin()
    transport = _make_http_transport(html=_FALLBACK_HTML)
    context = _make_context("python tutorial")

    results = await plugin.execute_search(context, transport)

    assert isinstance(results, list)
    assert len(results) >= 1
    assert all("/watch?v=" in r.url for r in results)


@pytest.mark.asyncio
async def test_youtube_execute_search_uses_navigate_for_browser_transport():
    """execute_search should use .navigate() when browser transport is provided."""
    plugin = YouTubePlugin()
    transport = _make_browser_transport(html=_YOUTUBE_HTML)
    context = _make_context("python tutorial")

    await plugin.execute_search(context, transport)

    transport.navigate.assert_called_once()
    called_url = transport.navigate.call_args[0][0]
    assert "youtube.com/results" in called_url


@pytest.mark.asyncio
async def test_youtube_execute_search_url_encodes_query():
    """Query spaces and special chars must be URL-encoded."""
    plugin = YouTubePlugin()
    transport = _make_http_transport(html="<html><body></body></html>")
    context = _make_context("cats playing piano")

    await plugin.execute_search(context, transport)

    called_url = transport.get.call_args[0][0]
    assert " " not in called_url
    assert "youtube.com" in called_url


# ---------------------------------------------------------------------------
# browse_result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_youtube_browse_result_returns_browse_action():
    """browse_result should return a BrowseAction."""
    plugin = YouTubePlugin()
    transport = _make_http_transport(html=_WATCH_PAGE_HTML, url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    context = _make_context()
    result = SearchResult(
        title="Never Gonna Give You Up",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        snippet="Official music video",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    assert isinstance(action, BrowseAction)


@pytest.mark.asyncio
async def test_youtube_browse_result_dwell_time_in_range():
    """Browse dwell time for YouTube should be between 30 and 120 seconds."""
    plugin = YouTubePlugin()
    transport = _make_http_transport(html=_WATCH_PAGE_HTML, url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    context = _make_context()
    result = SearchResult(
        title="Test Video",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        snippet="",
        position=1,
    )

    action = await plugin.browse_result(result, context, transport)

    # Must be within the 30–120s range modelling partial video watching
    assert 30.0 <= action.dwell_time_s <= 120.0


@pytest.mark.asyncio
async def test_youtube_browse_result_status_code():
    """BrowseAction.status_code should reflect the response status."""
    plugin = YouTubePlugin()
    transport = _make_http_transport(html=_WATCH_PAGE_HTML, status=200, url="https://www.youtube.com/watch?v=test")
    context = _make_context()
    result = SearchResult(title="Test", url="https://www.youtube.com/watch?v=test", snippet="", position=1)

    action = await plugin.browse_result(result, context, transport)

    assert action.status_code == 200
