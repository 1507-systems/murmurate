"""
plugins/wikipedia.py — Wikipedia plugin using the OpenSearch API + article HTML.

Wikipedia provides a clean OpenSearch-compatible API endpoint that returns
structured JSON with no authentication required. This makes it ideal for the
HTTP transport path — no JS rendering needed, lightweight, and fast.

Two-phase browsing:
  1. execute_search  — calls the opensearch API to get a list of article titles,
                       descriptions, and URLs for a given query.
  2. browse_result   — fetches the article HTML and extracts paragraph text +
                       internal wiki links for topic tree expansion.

The opensearch JSON response has the shape:
  [query_string, [titles], [descriptions], [urls]]

Both lists are guaranteed to be the same length by the Wikipedia API.
"""

from __future__ import annotations

import json
import random
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlparse

from murmurate.models import BrowseAction, SearchResult, SessionContext, TransportType
from murmurate.plugins.base import SitePlugin


# ---------------------------------------------------------------------------
# HTML parser helpers
# ---------------------------------------------------------------------------

class _WikiArticleParser(HTMLParser):
    """
    Extract paragraph text and anchor links from a Wikipedia article page.

    Wikipedia articles use standard <p> tags for body text and <a href>
    for internal (and external) links. We collect both for:
      - content_snippets: paragraph text fed into TF-IDF topic expansion
      - links_found: URLs for potential follow-on visits
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


def _extract_article_content(
    html: str,
    base_url: str,
    max_snippets: int = 5,
) -> tuple[list[str], list[str]]:
    """
    Parse a Wikipedia article page and return (absolute_links, text_snippets).

    Relative hrefs (e.g. /wiki/Python) are resolved to full Wikipedia URLs.
    Fragment-only anchors and non-HTTP links are dropped. Returns at most
    max_snippets paragraph strings.
    """
    parser = _WikiArticleParser()
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

class WikipediaPlugin(SitePlugin):
    """
    Site plugin for English Wikipedia using the OpenSearch API.

    Searches via the /w/api.php opensearch endpoint (returns JSON, no auth
    needed) and browses article pages by fetching standard article HTML.

    Wikipedia is generous with rate limits for good-faith crawlers, so we
    allow 30 RPM — still conservative relative to the official limit but
    fast enough for realistic browsing simulation.
    """

    @property
    def name(self) -> str:
        return "wikipedia"

    @property
    def domains(self) -> list[str]:
        return ["en.wikipedia.org"]

    @property
    def preferred_transport(self) -> TransportType:
        # Wikipedia is pure HTML/JSON — no JS required; HTTP is optimal
        return TransportType.HTTP

    @property
    def rate_limit_rpm(self) -> int:
        # Wikipedia's API is generous; 30 RPM is realistic for human simulation
        return 30

    async def execute_search(
        self,
        context: SessionContext,
        transport,
    ) -> list[SearchResult]:
        """
        Search Wikipedia using the opensearch API and return matching articles.

        The opensearch endpoint returns a four-element JSON array:
          [query, [titles], [descriptions], [urls]]

        All three inner lists have the same length and are zipped together to
        build SearchResult objects. If the API returns empty lists (no results),
        an empty list is returned without error.

        Args:
            context: Session context providing the current query and fingerprint.
            transport: Active transport with .get(url, fingerprint) coroutine.

        Returns:
            Ordered list of SearchResult objects (position is 1-indexed).
        """
        query = context.queries[context.current_query_index]
        encoded = quote_plus(query)
        url = (
            f"https://en.wikipedia.org/w/api.php"
            f"?action=opensearch&search={encoded}&limit=5&format=json"
        )

        response = await transport.get(url, context.persona.fingerprint)

        # The opensearch response is plain JSON in the body (html field)
        try:
            data = json.loads(response.html)
        except (json.JSONDecodeError, ValueError):
            return []

        # Validate the expected four-element structure
        if not isinstance(data, list) or len(data) < 4:
            return []

        _query_str, titles, descriptions, urls = data[0], data[1], data[2], data[3]

        # Guard against malformed responses where arrays have mismatched lengths
        count = min(len(titles), len(descriptions), len(urls))

        results: list[SearchResult] = []
        for i in range(count):
            results.append(
                SearchResult(
                    title=titles[i],
                    url=urls[i],
                    snippet=descriptions[i],
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
        Fetch a Wikipedia article and extract outbound links and paragraph text.

        Wikipedia articles have rich internal linking — every notable term is
        a wikilink. Those links are harvested for potential follow-on visits,
        making Wikipedia a natural source of topic tree expansion material.

        Dwell time is drawn from a wider distribution (10–60 s) than most sites
        because Wikipedia articles are longer and people actually read them.

        Args:
            result: The SearchResult to visit.
            context: Active session context for persona fingerprint.
            transport: Active transport exposing .get(url, fingerprint).

        Returns:
            BrowseAction recording the visit details and extracted content.
        """
        response = await transport.get(result.url, context.persona.fingerprint)

        links, snippets = _extract_article_content(
            response.html,
            base_url=result.url,
            max_snippets=5,
        )

        # Wikipedia articles are typically longer than average web pages;
        # model a correspondingly longer dwell time (10–60 seconds)
        dwell_time = random.uniform(10.0, 60.0)

        return BrowseAction(
            url_visited=result.url,
            dwell_time_s=dwell_time,
            links_found=links,
            content_snippets=snippets,
            status_code=response.status,
        )
