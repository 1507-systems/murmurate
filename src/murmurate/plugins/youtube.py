"""
plugins/youtube.py — YouTube search plugin using the HTML results page.

YouTube's results page is heavily JavaScript-driven; the video metadata is
embedded as a JSON blob inside a <script> tag of the form:
  var ytInitialData = {...};

We extract video IDs and titles from that blob using lightweight string
parsing rather than a full JSON parse — the blob is large and we only need
a few fields. If the JSON extraction fails we fall back to scanning the HTML
for /watch?v= hrefs.

Browse simulation for YouTube includes a configurable dwell time drawn from
30–120 seconds, representing a user watching part of a video. The full video
is never actually fetched; we only load the watch page HTML.

Because YouTube requires JavaScript to render its initial data, the preferred
transport is BROWSER. An HTTP transport will still work via the ytInitialData
script tag extraction path, giving degraded but functional results.
"""

from __future__ import annotations

import json
import random
import re
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlparse

from murmurate.models import BrowseAction, SearchResult, SessionContext, TransportType
from murmurate.plugins.base import SitePlugin


# ---------------------------------------------------------------------------
# HTML / JSON extraction helpers
# ---------------------------------------------------------------------------

class _WatchLinkParser(HTMLParser):
    """
    Fallback parser that scans raw HTML for /watch?v= anchor hrefs.

    Used when the ytInitialData JSON extraction path fails. Yields video IDs
    without titles or descriptions — titles are set to the video ID as a
    placeholder.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # Map video_id -> href to deduplicate
        self.video_links: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = next((v for k, v in attrs if k == "href" and v), None)
        if href and "/watch?v=" in href:
            # Extract the video ID (everything between v= and the next & or end)
            match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", href)
            if match:
                vid = match.group(1)
                if vid not in self.video_links:
                    self.video_links[vid] = f"https://www.youtube.com/watch?v={vid}"


def _extract_from_initial_data(html: str) -> list[tuple[str, str, str]]:
    """
    Extract (title, url, description) triples from YouTube's ytInitialData blob.

    YouTube embeds a JSON structure in a <script> tag:
      var ytInitialData = {...};

    We locate this with a regex, then walk the decoded JSON for
    videoRenderer objects which contain videoId, title, and
    descriptionSnippet fields.

    Returns an empty list on any parse failure — the caller falls back to
    the HTML anchor scanner.
    """
    # Extract the raw JSON blob (terminated by the first ; after the = )
    match = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", html, re.DOTALL)
    if not match:
        return []

    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return []

    results: list[tuple[str, str, str]] = []

    def _walk(obj) -> None:
        """Recursively search for videoRenderer objects."""
        if isinstance(obj, dict):
            if "videoId" in obj and "title" in obj:
                vid_id = obj["videoId"]
                # Title is nested: title.runs[0].text or title.simpleText
                title_obj = obj.get("title", {})
                runs = title_obj.get("runs", [])
                title = runs[0].get("text", "") if runs else title_obj.get("simpleText", "")
                # Description snippet similarly nested
                desc_obj = obj.get("descriptionSnippet", {})
                desc_runs = desc_obj.get("runs", [])
                description = " ".join(r.get("text", "") for r in desc_runs)
                if vid_id and title:
                    url = f"https://www.youtube.com/watch?v={vid_id}"
                    results.append((title, url, description))
            for value in obj.values():
                _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)
    return results


class _LinkAndTextExtractor(HTMLParser):
    """Extract anchor hrefs and paragraph text from an arbitrary page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.paragraphs: list[str] = []
        self._in_p = False
        self._p_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = next((v for k, v in attrs if k == "href" and v), None)
            if href:
                self.links.append(href)
        elif tag == "p":
            self._in_p = True
            self._p_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._in_p:
            text = "".join(self._p_parts).strip()
            if text:
                self.paragraphs.append(text)
            self._in_p = False
            self._p_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_p:
            self._p_parts.append(data)


def _extract_links_and_text(
    html: str,
    base_url: str,
    max_snippets: int = 5,
) -> tuple[list[str], list[str]]:
    """Parse HTML and return (absolute_links, text_snippets)."""
    parser = _LinkAndTextExtractor()
    parser.feed(html)

    seen: set[str] = set()
    links: list[str] = []
    for raw in parser.links:
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        absolute = urljoin(base_url, raw)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        no_frag = parsed._replace(fragment="").geturl()
        if no_frag not in seen:
            seen.add(no_frag)
            links.append(no_frag)

    return links, parser.paragraphs[:max_snippets]


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class YouTubePlugin(SitePlugin):
    """
    Site plugin for YouTube video search.

    Navigates to youtube.com/results and extracts video listings from either
    the embedded ytInitialData JSON blob or, as a fallback, from /watch?v=
    anchor hrefs. Because YouTube renders its result page with JavaScript,
    BROWSER transport is strongly preferred for complete data extraction.

    Browse simulation loads the watch page and dwells 30–120 seconds, which
    models realistic partial-video-watching behaviour without ever streaming
    actual video content.
    """

    @property
    def name(self) -> str:
        return "youtube"

    @property
    def domains(self) -> list[str]:
        return ["youtube.com", "www.youtube.com"]

    @property
    def preferred_transport(self) -> TransportType:
        # YouTube results page requires JS rendering for full data; BROWSER
        # transport is required for reliable extraction.
        return TransportType.BROWSER

    @property
    def rate_limit_rpm(self) -> int:
        # YouTube is sensitive to automated traffic; 5 RPM is conservative
        # but keeps the persona's behaviour within human-plausible bounds.
        return 5

    async def execute_search(
        self,
        context: SessionContext,
        transport,
    ) -> list[SearchResult]:
        """
        Search YouTube and return video results.

        Constructs a youtube.com/results URL, fetches the page, and attempts
        to extract video metadata from the embedded ytInitialData JSON blob.
        If that fails (e.g. HTTP transport without JS rendering), falls back
        to scanning anchor hrefs for /watch?v= patterns.

        Args:
            context: Session context providing the current query and fingerprint.
            transport: Active transport; BROWSER gives richer results.

        Returns:
            Ordered list of SearchResult objects (position 1-indexed).
        """
        query = context.queries[context.current_query_index]
        encoded = quote_plus(query)
        url = f"https://www.youtube.com/results?search_query={encoded}"

        # Use navigate() for browser transport, get() for HTTP transport
        if hasattr(transport, "navigate"):
            response = await transport.navigate(url, context.persona.fingerprint)
        else:
            response = await transport.get(url, context.persona.fingerprint)

        # Try the rich JSON extraction path first
        extracted = _extract_from_initial_data(response.html)

        if extracted:
            return [
                SearchResult(title=t, url=u, snippet=d, position=i + 1)
                for i, (t, u, d) in enumerate(extracted)
            ]

        # Fallback: scan raw HTML for watch links
        fallback_parser = _WatchLinkParser()
        fallback_parser.feed(response.html)

        results: list[SearchResult] = []
        for i, (vid_id, watch_url) in enumerate(fallback_parser.video_links.items()):
            results.append(
                SearchResult(
                    title=vid_id,   # No title available via this path
                    url=watch_url,
                    snippet="",
                    position=i + 1,
                )
            )

        return results

    async def browse_result(
        self,
        result: SearchResult,
        context: SessionContext,
        transport,
    ) -> BrowseAction:
        """
        Navigate to a YouTube video page and simulate watching.

        Loads the watch page HTML to extract video metadata and related links.
        Dwells for 30–120 seconds to model realistic partial video consumption.
        The actual video stream is never fetched — this is page-level simulation.

        Args:
            result: The SearchResult (video) to visit.
            context: Active session context for persona fingerprint.
            transport: Active transport.

        Returns:
            BrowseAction with the watch URL, dwell time, related video links,
            and any text snippets found on the page.
        """
        if hasattr(transport, "navigate"):
            response = await transport.navigate(result.url, context.persona.fingerprint)
        else:
            response = await transport.get(result.url, context.persona.fingerprint)

        links, snippets = _extract_links_and_text(
            response.html,
            base_url=result.url,
            max_snippets=5,
        )

        # Model realistic video watch dwell time: 30–120 seconds
        # (most users watch a portion of a video, not the full length)
        dwell_time = random.uniform(30.0, 120.0)

        return BrowseAction(
            url_visited=result.url,
            dwell_time_s=dwell_time,
            links_found=links,
            content_snippets=snippets,
            status_code=response.status,
        )
