"""
plugins/reddit.py — Reddit search plugin using old.reddit.com.

old.reddit.com is the classic Reddit interface that returns standard, largely
JavaScript-free HTML. It is significantly easier to parse than new.reddit.com,
which renders everything in React and requires a browser to produce readable
content.

Search results appear as <div class="search-result-link"> containers, each
containing:
  - <a class="search-result-link" href="...">: the post title + URL
  - <div class="search-result-meta">: subreddit, author, score, timestamp

Post detail pages contain:
  - <div class="entry">: the post title
  - <div class="sitetable"> → <div class="usertext-body">: post body text
  - <div class="comment"> → <div class="usertext-body">: comment text

We use HTTP transport (preferred_transport = HTTP) since old.reddit.com works
without JavaScript. The rate limit is relatively generous at 15 RPM because
Reddit's API guidelines allow automated access at these rates for good-faith
scrapers.
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

class _RedditSearchParser(HTMLParser):
    """
    Parse old.reddit.com search result HTML to extract post listings.

    Search results on old.reddit.com use this structure:
      <div class="search-result-link">
        <div class="search-result-header">
          <a class="search-result-link" href="/r/sub/comments/id/title/">Title text</a>
        </div>
        <div class="search-result-meta">
          ... subreddit / author / score info ...
        </div>
      </div>

    We look for anchor tags with href containing /comments/ and harvest
    the link text as the title.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[tuple[str, str, str]] = []

        self._in_result_div: bool = False
        self._result_depth: int = 0
        self._in_link: bool = False
        self._link_parts: list[str] = []
        self._link_href: str | None = None
        self._in_meta: bool = False
        self._meta_parts: list[str] = []
        self._pending_title: str | None = None
        self._pending_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        classes = set((attr_dict.get("class") or "").split())

        if tag == "div" and "search-result-link" in classes:
            # Entering a result container
            self._in_result_div = True
            self._result_depth = 1
            self._pending_title = None
            self._pending_url = None

        elif tag == "div" and self._in_result_div:
            self._result_depth += 1
            if "search-result-meta" in classes:
                self._in_meta = True
                self._meta_parts = []

        elif tag == "a" and self._in_result_div and not self._in_meta:
            href = attr_dict.get("href", "")
            # Post links contain /comments/
            if href and "/comments/" in href:
                # Resolve relative reddit URLs
                if href.startswith("/"):
                    href = f"https://old.reddit.com{href}"
                self._in_link = True
                self._link_parts = []
                self._link_href = href

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            title = "".join(self._link_parts).strip()
            if title and self._link_href:
                self._pending_title = title
                self._pending_url = self._link_href
            self._in_link = False
            self._link_parts = []
            self._link_href = None

        elif tag == "div" and self._in_meta:
            meta = "".join(self._meta_parts).strip()
            self._in_meta = False
            self._meta_parts = []
            # We use the meta text (subreddit + score) as the snippet
            if self._pending_title and self._pending_url:
                self.results.append((self._pending_title, self._pending_url, meta))
                self._pending_title = None
                self._pending_url = None

        elif tag == "div" and self._in_result_div:
            self._result_depth -= 1
            if self._result_depth <= 0:
                # Leaving result container without finding meta — emit with empty snippet
                if self._pending_title and self._pending_url:
                    self.results.append((self._pending_title, self._pending_url, ""))
                    self._pending_title = None
                    self._pending_url = None
                self._in_result_div = False
                self._result_depth = 0

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._link_parts.append(data)
        elif self._in_meta:
            self._meta_parts.append(data)


class _RedditPostParser(HTMLParser):
    """
    Parse an old.reddit.com post page to extract body text and comments.

    Post body lives in:
      <div class="entry"> … <div class="usertext-body"> <p>...</p>

    Comments live in similar usertext-body divs nested inside .comment divs.
    We collect paragraphs from both. Outbound links (href) are also collected
    for follow-on visit candidates.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.links: list[str] = []

        self._in_usertext: bool = False
        self._usertext_depth: int = 0
        self._in_p: bool = False
        self._p_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        classes = set((attr_dict.get("class") or "").split())

        if tag == "a":
            href = attr_dict.get("href", "")
            if href:
                self.links.append(href)

        elif tag == "div" and "usertext-body" in classes:
            self._in_usertext = True
            self._usertext_depth = 1

        elif tag == "div" and self._in_usertext:
            self._usertext_depth += 1

        elif tag == "p" and self._in_usertext:
            self._in_p = True
            self._p_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._in_p:
            text = "".join(self._p_parts).strip()
            if text:
                self.paragraphs.append(text)
            self._in_p = False
            self._p_parts = []

        elif tag == "div" and self._in_usertext:
            self._usertext_depth -= 1
            if self._usertext_depth <= 0:
                self._in_usertext = False

    def handle_data(self, data: str) -> None:
        if self._in_p:
            self._p_parts.append(data)


def _extract_post_content(
    html: str,
    base_url: str,
    max_snippets: int = 5,
) -> tuple[list[str], list[str]]:
    """Parse a Reddit post page and return (absolute_links, text_snippets)."""
    parser = _RedditPostParser()
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

class RedditPlugin(SitePlugin):
    """
    Site plugin for Reddit search using old.reddit.com.

    old.reddit.com returns clean, parseable HTML without JavaScript requirements,
    making it ideal for HTTP transport. Search results and post content are
    extracted with lightweight HTMLParser state machines.

    The 15 RPM rate limit is conservative but aligns with Reddit's unofficial
    guidelines for non-API automated access.
    """

    @property
    def name(self) -> str:
        return "reddit"

    @property
    def domains(self) -> list[str]:
        return ["reddit.com", "old.reddit.com"]

    @property
    def preferred_transport(self) -> TransportType:
        # old.reddit.com is JavaScript-free; HTTP is both sufficient and optimal
        return TransportType.HTTP

    @property
    def rate_limit_rpm(self) -> int:
        # Reddit is relatively lenient; 15 RPM keeps us in good-citizen territory
        return 15

    async def execute_search(
        self,
        context: SessionContext,
        transport,
    ) -> list[SearchResult]:
        """
        Search Reddit via old.reddit.com/search and return post listings.

        Uses old.reddit.com which provides clean HTML without JavaScript.
        Parses result containers to extract post titles, URLs, and meta
        information (subreddit, score) as snippets.

        Args:
            context: Session context providing the current query and fingerprint.
            transport: Active transport with .get(url, fingerprint) coroutine.

        Returns:
            Ordered list of SearchResult objects (position 1-indexed).
        """
        query = context.queries[context.current_query_index]
        encoded = quote_plus(query)
        url = f"https://old.reddit.com/search?q={encoded}"

        response = await transport.get(url, context.persona.fingerprint)

        parser = _RedditSearchParser()
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
        Fetch a Reddit post and extract body text and comments.

        Navigates to the post URL on old.reddit.com (rewrites reddit.com URLs
        to old.reddit.com for consistency). Extracts post body and top comments
        from usertext-body divs. Dwell time (20–120 seconds) models reading a
        post thread — threads with many comments warrant longer dwell.

        Args:
            result: The SearchResult (post) to visit.
            context: Active session context for persona fingerprint.
            transport: Active transport exposing .get(url, fingerprint).

        Returns:
            BrowseAction with post content as snippets.
        """
        # Rewrite new.reddit.com URLs to old.reddit.com for cleaner HTML
        visit_url = result.url.replace("www.reddit.com", "old.reddit.com").replace(
            "reddit.com", "old.reddit.com"
        )
        # Avoid double-rewriting already-old URLs
        visit_url = visit_url.replace("old.old.reddit.com", "old.reddit.com")

        response = await transport.get(visit_url, context.persona.fingerprint)

        links, snippets = _extract_post_content(
            response.html,
            base_url=visit_url,
            max_snippets=5,
        )

        # Reddit threads range from single posts to long discussions;
        # model dwell time across that full range.
        dwell_time = random.uniform(20.0, 120.0)

        return BrowseAction(
            url_visited=visit_url,
            dwell_time_s=dwell_time,
            links_found=links,
            content_snippets=snippets,
            status_code=response.status,
        )
