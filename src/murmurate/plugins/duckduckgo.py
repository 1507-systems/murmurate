"""
plugins/duckduckgo.py — DuckDuckGo search plugin using the lite HTML interface.

DuckDuckGo's html.duckduckgo.com endpoint returns clean, JavaScript-free HTML
that is far easier to parse than the JS-heavy main site. This means we can use
HTTP transport rather than a full browser, keeping resource usage low and
avoiding Playwright overhead for a simple SERP scrape.

HTML structure of DDG lite results (as of 2026):
  <div class="result ...">
    <a class="result__a" href="...">Title text</a>
    <a class="result__snippet">Snippet text</a>
  </div>

We use stdlib html.parser to avoid any extra dependencies — the parsing needs
are simple enough that BeautifulSoup would be overkill.
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

class _DDGResultParser(HTMLParser):
    """
    Parse DDG lite HTML to extract search result titles, URLs, and snippets.

    The lite DDG SERP has this structure (simplified):
      <a class="result__a" href="URL">Title</a>
      <a class="result__snippet">Snippet text</a>

    We track the state machine: when we encounter a tag with class
    "result__a" we record the href and start collecting the link text as the
    title. When we encounter "result__snippet" we start collecting text for
    the snippet.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        # Completed (title, url, snippet) triples
        self.results: list[tuple[str, str, str]] = []

        # --- transient state during parsing ---
        # Title link href accumulated from the current result__a tag
        self._current_href: str | None = None
        # Text accumulated while inside a result__a or result__snippet tag
        self._collecting_title: bool = False
        self._collecting_snippet: bool = False
        self._current_title_parts: list[str] = []
        self._current_snippet_parts: list[str] = []

        # Buffer: once we have a title+url, we wait for the matching snippet
        self._pending_title: str | None = None
        self._pending_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return

        classes = {
            c.strip()
            for attr_name, attr_val in attrs
            if attr_name == "class" and attr_val
            for c in attr_val.split()
        }

        href = next(
            (val for name, val in attrs if name == "href" and val),
            None,
        )

        if "result__a" in classes and href:
            # Start of a new result link — record href, start title collection
            self._current_href = href
            self._collecting_title = True
            self._current_title_parts = []

        elif "result__snippet" in classes:
            # Start of snippet for the most-recently-seen result__a
            self._collecting_snippet = True
            self._current_snippet_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "a":
            return

        if self._collecting_title:
            title = "".join(self._current_title_parts).strip()
            self._collecting_title = False
            self._current_title_parts = []
            if title and self._current_href:
                # Park this title+url until we find the matching snippet
                self._pending_title = title
                self._pending_url = self._current_href
            self._current_href = None

        elif self._collecting_snippet:
            snippet = "".join(self._current_snippet_parts).strip()
            self._collecting_snippet = False
            self._current_snippet_parts = []
            if self._pending_title and self._pending_url:
                self.results.append((self._pending_title, self._pending_url, snippet))
                self._pending_title = None
                self._pending_url = None

    def handle_data(self, data: str) -> None:
        if self._collecting_title:
            self._current_title_parts.append(data)
        elif self._collecting_snippet:
            self._current_snippet_parts.append(data)


class _LinkAndTextExtractor(HTMLParser):
    """
    Minimal parser that collects <a href> links and <p> text from a generic page.

    Used by browse_result to extract outbound links and content snippets for
    TF-IDF topic expansion.
    """

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
    """
    Parse HTML and return (absolute_links, text_snippets).

    Relative hrefs are resolved to absolute URLs. Fragment-only and empty
    hrefs are dropped. Returns at most max_snippets paragraph strings.
    """
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

class DuckDuckGoPlugin(SitePlugin):
    """
    Site plugin for DuckDuckGo using the lite/html endpoint.

    Uses html.duckduckgo.com which returns plain HTML results without
    JavaScript, making it safe and efficient to parse with HTTP transport.
    The rate limit is kept conservative (10 RPM) to avoid triggering
    DDG's bot-detection mechanisms.
    """

    @property
    def name(self) -> str:
        return "duckduckgo"

    @property
    def domains(self) -> list[str]:
        return ["duckduckgo.com", "html.duckduckgo.com"]

    @property
    def preferred_transport(self) -> TransportType:
        # The lite endpoint works with plain HTTP; EITHER lets the scheduler
        # decide whether to use HTTP or browser based on system load.
        return TransportType.EITHER

    @property
    def rate_limit_rpm(self) -> int:
        # DDG lite has documented bot-detection; stay well below the threshold
        return 10

    async def execute_search(
        self,
        context: SessionContext,
        transport,
    ) -> list[SearchResult]:
        """
        Fetch DuckDuckGo lite HTML and parse result titles, URLs, and snippets.

        Uses the html.duckduckgo.com endpoint which returns static HTML with no
        JavaScript dependency. The query is URL-encoded with quote_plus so spaces
        become '+' characters, matching how browsers submit form data to DDG.

        Args:
            context: The active session context; provides the current query and
                     persona fingerprint for header injection.
            transport: Active transport instance; must expose a .get(url, fingerprint)
                       coroutine returning an object with .status and .html fields.

        Returns:
            Ordered list of SearchResult objects (position is 1-indexed).
            Returns an empty list if the page contains no parseable results.
        """
        query = context.queries[context.current_query_index]
        encoded = quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"

        response = await transport.get(url, context.persona.fingerprint)

        # Parse the DDG lite HTML into (title, url, snippet) triples
        parser = _DDGResultParser()
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
        Fetch a search result page and extract outbound links and text snippets.

        Simulates a realistic dwell time drawn from a uniform distribution
        (5–30 seconds) to mimic real user reading behaviour. Links and paragraph
        text are extracted for use in downstream TF-IDF topic expansion.

        Args:
            result: The SearchResult to visit.
            context: Active session context for persona fingerprint.
            transport: Active transport exposing .get(url, fingerprint).

        Returns:
            BrowseAction recording the visit URL, dwell time, links, snippets,
            and HTTP status code.
        """
        response = await transport.get(result.url, context.persona.fingerprint)

        links, snippets = _extract_links_and_text(
            response.html,
            base_url=result.url,
            max_snippets=5,
        )

        # Simulate a realistic dwell time between 5 and 30 seconds
        dwell_time = random.uniform(5.0, 30.0)

        return BrowseAction(
            url_visited=result.url,
            dwell_time_s=dwell_time,
            links_found=links,
            content_snippets=snippets,
            status_code=response.status,
        )
