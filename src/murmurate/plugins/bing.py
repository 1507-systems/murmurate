"""
plugins/bing.py — Bing Search plugin using the standard HTML results page.

Bing's search results page (bing.com/search?q=<query>) returns clean HTML
with a well-structured result format. Each organic result appears inside a
<li class="b_algo"> element containing:
  - <h2><a href="...">Title text</a></h2>  → title + URL
  - <div class="b_caption"><p>...</p>       → snippet text

This structure has been consistent across multiple years and is significantly
more parseable than Google's result HTML. EITHER transport is declared since
Bing works well with both HTTP and browser transports.

Rate limit is set to 12 RPM — Bing's bot detection is somewhat more lenient
than Google's but still enforces rate-based blocking at higher frequencies.
"""

from __future__ import annotations

import random
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlparse

from murmurate.models import BrowseAction, SearchResult, SessionContext, TransportType
from murmurate.plugins.base import SitePlugin


# ---------------------------------------------------------------------------
# HTML parser helpers
# ---------------------------------------------------------------------------

class _BingResultParser(HTMLParser):
    """
    Parse Bing search result HTML to extract titles, URLs, and snippets.

    Bing SERP structure (simplified):
      <li class="b_algo">
        <h2><a href="https://result-url.com">Title text</a></h2>
        <div class="b_caption">
          <p>Snippet text here.</p>
        </div>
      </li>

    State machine:
      1. Detect <li class="b_algo"> → enter a result block
      2. Inside the block, <h2><a> gives us title text and URL
      3. <div class="b_caption"> <p> gives us the snippet
      4. </li> closes the block and emits the result
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        # Completed (title, url, snippet) triples
        self.results: list[tuple[str, str, str]] = []

        # --- transient state ---
        self._in_algo: bool = False
        self._algo_depth: int = 0  # li nesting depth
        self._in_h2: bool = False
        self._in_h2_link: bool = False
        self._h2_link_parts: list[str] = []
        self._h2_link_href: str | None = None
        self._pending_title: str | None = None
        self._pending_url: str | None = None
        self._in_caption: bool = False
        self._caption_depth: int = 0
        self._in_caption_p: bool = False
        self._caption_p_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        classes = set((attr_dict.get("class") or "").split())

        if tag == "li" and "b_algo" in classes:
            # Start of an organic result block
            self._in_algo = True
            self._algo_depth = 1
            self._pending_title = None
            self._pending_url = None
            self._in_caption = False

        elif tag == "li" and self._in_algo:
            self._algo_depth += 1

        elif tag == "h2" and self._in_algo:
            self._in_h2 = True

        elif tag == "a" and self._in_h2:
            href = attr_dict.get("href", "")
            if href and href.startswith("http"):
                self._in_h2_link = True
                self._h2_link_parts = []
                self._h2_link_href = href

        elif tag == "div" and self._in_algo and "b_caption" in classes:
            self._in_caption = True
            self._caption_depth = 1

        elif tag == "div" and self._in_caption:
            self._caption_depth += 1

        elif tag == "p" and self._in_caption and not self._in_caption_p:
            self._in_caption_p = True
            self._caption_p_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_h2_link:
            title = "".join(self._h2_link_parts).strip()
            if title and self._h2_link_href:
                self._pending_title = title
                self._pending_url = self._h2_link_href
            self._in_h2_link = False
            self._h2_link_parts = []
            self._h2_link_href = None

        elif tag == "h2" and self._in_h2:
            self._in_h2 = False

        elif tag == "p" and self._in_caption_p:
            snippet = "".join(self._caption_p_parts).strip()
            if self._pending_title and self._pending_url:
                self.results.append((self._pending_title, self._pending_url, snippet))
                self._pending_title = None
                self._pending_url = None
            self._in_caption_p = False
            self._caption_p_parts = []

        elif tag == "div" and self._in_caption:
            self._caption_depth -= 1
            if self._caption_depth <= 0:
                self._in_caption = False

        elif tag == "li" and self._in_algo:
            self._algo_depth -= 1
            if self._algo_depth <= 0:
                # Emit any pending result that didn't have a caption paragraph
                if self._pending_title and self._pending_url:
                    self.results.append((self._pending_title, self._pending_url, ""))
                    self._pending_title = None
                    self._pending_url = None
                self._in_algo = False
                self._algo_depth = 0

    def handle_data(self, data: str) -> None:
        if self._in_h2_link:
            self._h2_link_parts.append(data)
        elif self._in_caption_p:
            self._caption_p_parts.append(data)


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

class BingPlugin(SitePlugin):
    """
    Site plugin for Bing Search using the standard HTML results page.

    Bing's SERP HTML uses a clean <li class="b_algo"> structure that is
    more consistent and parseable than Google's equivalent. Works well with
    both HTTP and browser transports (EITHER is declared).

    Rate limit is 12 RPM — slightly more generous than Google but still
    conservative enough to avoid triggering Bing's automated-traffic detection.
    """

    @property
    def name(self) -> str:
        return "bing"

    @property
    def domains(self) -> list[str]:
        return ["bing.com", "www.bing.com"]

    @property
    def preferred_transport(self) -> TransportType:
        # Bing's HTML results work with both HTTP and browser; EITHER lets
        # the scheduler choose the most efficient option.
        return TransportType.EITHER

    @property
    def rate_limit_rpm(self) -> int:
        # Slightly more lenient than Google's threshold; 12 RPM stays
        # comfortably within human-plausible browsing rates.
        return 12

    async def execute_search(
        self,
        context: SessionContext,
        transport,
    ) -> list[SearchResult]:
        """
        Search Bing and return organic result listings.

        Fetches bing.com/search?q=<query> and parses <li class="b_algo">
        elements to extract titles, URLs, and snippet paragraphs. Bing's
        HTML structure is stable enough that this approach works reliably
        without browser rendering.

        Args:
            context: Session context providing the current query and fingerprint.
            transport: Active transport with .get(url, fingerprint) coroutine.

        Returns:
            Ordered list of SearchResult objects (position 1-indexed).
        """
        query = context.queries[context.current_query_index]
        encoded = quote_plus(query)
        url = f"https://www.bing.com/search?q={encoded}"

        response = await transport.get(url, context.persona.fingerprint)

        parser = _BingResultParser()
        parser.feed(response.html)

        results: list[SearchResult] = []
        for i, (title, href, snippet) in enumerate(parser.results, start=1):
            results.append(
                SearchResult(
                    title=title,
                    url=href,
                    snippet=snippet,
                    position=i,
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
        Fetch a Bing search result page and extract outbound links and text.

        Simulates a realistic dwell time (8–45 seconds) drawn from a uniform
        distribution, matching the dwell time model used for Google results
        (both are general web search destinations with similar reading patterns).

        Args:
            result: The SearchResult to visit.
            context: Active session context for persona fingerprint.
            transport: Active transport exposing .get(url, fingerprint).

        Returns:
            BrowseAction recording the visit URL, dwell time, links, and
            content snippets.
        """
        response = await transport.get(result.url, context.persona.fingerprint)

        links, snippets = _extract_links_and_text(
            response.html,
            base_url=result.url,
            max_snippets=5,
        )

        # Bing result pages have similar reading patterns to Google results
        dwell_time = random.uniform(8.0, 45.0)

        return BrowseAction(
            url_visited=result.url,
            dwell_time_s=dwell_time,
            links_found=links,
            content_snippets=snippets,
            status_code=response.status,
        )
