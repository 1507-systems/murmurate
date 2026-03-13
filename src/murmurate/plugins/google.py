"""
plugins/google.py — Google Search plugin using the standard HTML results page.

Google's search results page embeds result links in anchor tags with an href
of the form /url?q=<encoded_url>&... These are Google redirect URLs that track
clicks before sending the user to the final destination. We extract the `q`
parameter value to recover the actual target URL.

Result titles appear as <h3> elements inside the same container as the redirect
link. Snippets appear in <div> elements with a data-sncf attribute or in
<span> elements immediately after the title block.

"People Also Ask" boxes contain additional question strings we can surface as
extra results with empty snippets — they provide topic expansion signals even
without full snippet text.

HTML parsing uses stdlib html.parser throughout — no external dependencies.
"""

from __future__ import annotations

import random
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs

from murmurate.models import BrowseAction, SearchResult, SessionContext, TransportType
from murmurate.plugins.base import SitePlugin


# ---------------------------------------------------------------------------
# HTML parser helpers
# ---------------------------------------------------------------------------

class _GoogleResultParser(HTMLParser):
    """
    Parse Google search result HTML to extract titles, URLs, and snippets.

    Google's SERP HTML embeds result links as anchor tags with href values
    like /url?q=<encoded_url>. We detect these and pair them with the
    preceding <h3> text for the title and trailing text content for the snippet.

    State machine:
      - When we enter an <a> with href containing '/url?q=', we decode the
        target URL and start tracking.
      - <h3> text inside such a link becomes the title.
      - Text in the following sibling <div> or <span> becomes the snippet.

    "People Also Ask" entries appear as <div data-q="..."> or similar; we
    collect question text from those spans as bonus topic expansion entries.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        # Completed (title, url, snippet) triples
        self.results: list[tuple[str, str, str]] = []

        # --- transient state ---
        # Are we inside a result anchor?
        self._in_result_link: bool = False
        # The decoded destination URL for the current result
        self._current_url: str | None = None
        # Are we collecting an <h3> title inside a result link?
        self._in_h3: bool = False
        self._h3_parts: list[str] = []
        # Pending title waiting for a snippet
        self._pending_title: str | None = None
        self._pending_url: str | None = None
        # Are we in a snippet container? (div immediately after a result)
        self._in_snippet: bool = False
        self._snippet_parts: list[str] = []
        # Nesting depth inside the snippet div so we know when it ends
        self._snippet_depth: int = 0

        # "People also ask" question collector
        self._in_paa_span: bool = False
        self._paa_parts: list[str] = []
        self.paa_questions: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)

        if tag == "a":
            href = attr_dict.get("href", "")
            if href and "/url?q=" in href:
                # Extract the real destination from Google's redirect URL
                try:
                    qs_part = href.split("/url?")[1]
                    params = parse_qs(qs_part)
                    target = params.get("q", [None])[0]
                    if target and target.startswith("http"):
                        self._in_result_link = True
                        self._current_url = target
                except Exception:
                    pass

        elif tag == "h3" and self._in_result_link:
            # Title heading inside a result link
            self._in_h3 = True
            self._h3_parts = []

        elif tag == "div" and self._pending_url and not self._in_snippet:
            # A div appearing after we have a pending title/url may be the snippet
            self._in_snippet = True
            self._snippet_parts = []
            self._snippet_depth = 1

        elif tag == "div" and self._in_snippet:
            self._snippet_depth += 1

        # "People also ask" boxes often use <span> inside a container
        # with a data-q or jsname attribute bearing the question text.
        # We check for spans inside a jscontroller block or data-hveid.
        elif tag == "span":
            jsname = attr_dict.get("jsname", "")
            if jsname:
                self._in_paa_span = True
                self._paa_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._in_h3:
            title = "".join(self._h3_parts).strip()
            self._in_h3 = False
            self._h3_parts = []
            if title and self._current_url:
                self._pending_title = title
                self._pending_url = self._current_url
            self._in_result_link = False
            self._current_url = None

        elif tag == "div" and self._in_snippet:
            self._snippet_depth -= 1
            if self._snippet_depth <= 0:
                snippet = "".join(self._snippet_parts).strip()
                self._in_snippet = False
                self._snippet_parts = []
                if self._pending_title and self._pending_url:
                    self.results.append((self._pending_title, self._pending_url, snippet))
                    self._pending_title = None
                    self._pending_url = None

        elif tag == "span" and self._in_paa_span:
            question = "".join(self._paa_parts).strip()
            if question and "?" in question:
                self.paa_questions.append(question)
            self._in_paa_span = False
            self._paa_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_h3:
            self._h3_parts.append(data)
        elif self._in_snippet:
            self._snippet_parts.append(data)
        elif self._in_paa_span:
            self._paa_parts.append(data)


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

class GooglePlugin(SitePlugin):
    """
    Site plugin for Google Search using the standard HTML results page.

    Uses google.com/search which returns HTML that, while JavaScript-heavy
    in a browser, contains the essential result data in its raw HTML form
    when fetched with an HTTP transport. EITHER transport is declared so the
    scheduler may use a browser if the HTTP approach is blocked.

    Rate limit is kept at 10 RPM — Google aggressively rate-limits automated
    traffic and CAPTCHA-triggers begin well below human-level usage rates.
    """

    @property
    def name(self) -> str:
        return "google"

    @property
    def domains(self) -> list[str]:
        return ["google.com", "www.google.com"]

    @property
    def preferred_transport(self) -> TransportType:
        # Google works via HTTP for basic result extraction; EITHER lets the
        # scheduler escalate to browser if HTTP gets blocked.
        return TransportType.EITHER

    @property
    def rate_limit_rpm(self) -> int:
        # Conservative — Google bot-detection kicks in quickly at higher rates
        return 10

    async def execute_search(
        self,
        context: SessionContext,
        transport,
    ) -> list[SearchResult]:
        """
        Fetch Google search results and parse titles, URLs, and snippets.

        Constructs a standard google.com/search URL with the query encoded
        using quote_plus (space → +). Parses the /url?q= redirect hrefs to
        extract real destination URLs, and pairs them with adjacent <h3>
        title text and snippet divs.

        "People Also Ask" questions are appended as additional results with
        empty snippets — they carry topical signal even without full content.

        Args:
            context: Session context providing the current query and fingerprint.
            transport: Active transport with .get(url, fingerprint) coroutine.

        Returns:
            Ordered list of SearchResult objects (position is 1-indexed).
            Returns empty list if no results can be parsed.
        """
        query = context.queries[context.current_query_index]
        encoded = quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}"

        response = await transport.get(url, context.persona.fingerprint)

        parser = _GoogleResultParser()
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

        # Append "People Also Ask" questions as bonus results for topic expansion
        base_pos = len(results) + 1
        for j, question in enumerate(parser.paa_questions):
            results.append(
                SearchResult(
                    title=question,
                    url=url,  # Points back to the SERP — no individual page
                    snippet="",
                    position=base_pos + j,
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
        Fetch a search result page and extract outbound links and text.

        Simulates a realistic dwell time (8–45 seconds) drawn from a uniform
        distribution. Google users tend to spend moderate time on result pages
        before hitting back or navigating deeper.

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

        # Google result pages vary widely in content density; model dwell time
        # accordingly with a wider range than e.g. DDG.
        dwell_time = random.uniform(8.0, 45.0)

        return BrowseAction(
            url_visited=result.url,
            dwell_time_s=dwell_time,
            links_found=links,
            content_snippets=snippets,
            status_code=response.status,
        )
