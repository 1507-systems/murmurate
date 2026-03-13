"""
plugins/amazon.py — Amazon product search plugin.

Amazon's search results page (amazon.com/s?k=<query>) embeds product listings
in <div data-component-type="s-search-result"> elements. Each result contains:
  - data-asin attribute: the Amazon Standard Identification Number (ASIN)
  - <h2><a> with the product title and href to the product detail page
  - <span class="a-price-whole"> for the price integer part
  - <span class="a-price-fraction"> for the cents

We use a lightweight HTMLParser state machine to extract these fields. Amazon's
HTML is complex enough that we aim for "good enough" extraction rather than
perfect coverage — partial results are preferable to hard failures.

Product detail pages (browse_result) contain the full title in an <span
id="productTitle"> element and a description in the feature bullets list
(<ul id="feature-bullets">). We extract both plus outbound links.
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

class _AmazonSearchParser(HTMLParser):
    """
    Parse Amazon search results HTML to extract product listings.

    Each search result is a <div data-component-type="s-search-result"
    data-asin="..."> container. Inside it we look for:
      - <h2><a href="...">Title text</a></h2>  → title + URL
      - <span class="a-price-whole">N</span>   → price integer
      - <span class="a-price-fraction">NN</span> → price decimal

    We combine price parts into a snippet string like "$12.99".
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        # Completed (title, url, snippet) triples
        self.results: list[tuple[str, str, str]] = []

        # --- transient state ---
        # Are we inside a result div?
        self._in_result: bool = False
        # Current result's ASIN (used to validate we're in a result block)
        self._current_asin: str | None = None
        # Nesting depth inside the result div so we know when it ends
        self._result_depth: int = 0

        # Are we collecting an <h2> title link?
        self._in_h2: bool = False
        self._in_title_link: bool = False
        self._title_parts: list[str] = []
        self._title_href: str | None = None

        # Pending title+url waiting for price to form snippet
        self._pending_title: str | None = None
        self._pending_url: str | None = None

        # Price collection
        self._in_price_whole: bool = False
        self._in_price_fraction: bool = False
        self._price_whole: str = ""
        self._price_fraction: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)

        if tag == "div":
            comp_type = attr_dict.get("data-component-type", "")
            asin = attr_dict.get("data-asin", "")
            if comp_type == "s-search-result" and asin:
                # Entering a new result container
                self._in_result = True
                self._current_asin = asin
                self._result_depth = 1
                self._pending_title = None
                self._pending_url = None
                self._price_whole = ""
                self._price_fraction = ""
            elif self._in_result:
                self._result_depth += 1

        elif tag == "h2" and self._in_result:
            self._in_h2 = True

        elif tag == "a" and self._in_h2:
            href = attr_dict.get("href", "")
            if href:
                # Product hrefs are relative: /dp/ASIN/...
                if href.startswith("/"):
                    href = f"https://www.amazon.com{href}"
                self._in_title_link = True
                self._title_parts = []
                self._title_href = href

        elif tag == "span" and self._in_result:
            classes = set((attr_dict.get("class") or "").split())
            if "a-price-whole" in classes:
                self._in_price_whole = True
            elif "a-price-fraction" in classes:
                self._in_price_fraction = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title_link:
            title = "".join(self._title_parts).strip()
            if title and self._title_href:
                self._pending_title = title
                self._pending_url = self._title_href
            self._in_title_link = False
            self._title_parts = []
            self._title_href = None

        elif tag == "h2" and self._in_h2:
            self._in_h2 = False

        elif tag == "div" and self._in_result:
            self._result_depth -= 1
            if self._result_depth <= 0:
                # Leaving the result container — emit what we have
                if self._pending_title and self._pending_url:
                    price = ""
                    if self._price_whole:
                        price = f"${self._price_whole}"
                        if self._price_fraction:
                            price += f".{self._price_fraction}"
                    self.results.append(
                        (self._pending_title, self._pending_url, price)
                    )
                self._in_result = False
                self._current_asin = None
                self._result_depth = 0
                self._pending_title = None
                self._pending_url = None

        elif tag == "span":
            if self._in_price_whole:
                self._in_price_whole = False
            elif self._in_price_fraction:
                self._in_price_fraction = False

    def handle_data(self, data: str) -> None:
        if self._in_title_link:
            self._title_parts.append(data)
        elif self._in_price_whole:
            self._price_whole += data.strip()
        elif self._in_price_fraction:
            self._price_fraction += data.strip()


class _AmazonProductParser(HTMLParser):
    """
    Parse an Amazon product detail page to extract title, bullets, and links.

    Targets:
      - <span id="productTitle">: product title
      - <ul id="feature-bullets"> <li> <span>: feature bullet points
      - <a href>: all outbound links
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str = ""
        self.bullets: list[str] = []
        self.links: list[str] = []

        self._in_product_title: bool = False
        self._title_parts: list[str] = []
        self._in_feature_bullets: bool = False
        self._bullets_depth: int = 0
        self._in_bullet_span: bool = False
        self._bullet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)

        if tag == "a":
            href = attr_dict.get("href", "")
            if href:
                self.links.append(href)

        elif tag == "span":
            id_ = attr_dict.get("id", "")
            if id_ == "productTitle":
                self._in_product_title = True
                self._title_parts = []

        elif tag == "ul":
            id_ = attr_dict.get("id", "")
            if id_ == "feature-bullets":
                self._in_feature_bullets = True
                self._bullets_depth = 1

        elif tag == "ul" and self._in_feature_bullets:
            self._bullets_depth += 1

        elif tag == "span" and self._in_feature_bullets:
            self._in_bullet_span = True
            self._bullet_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._in_product_title:
            self.title = "".join(self._title_parts).strip()
            self._in_product_title = False

        elif tag == "span" and self._in_bullet_span:
            bullet = "".join(self._bullet_parts).strip()
            if bullet:
                self.bullets.append(bullet)
            self._in_bullet_span = False
            self._bullet_parts = []

        elif tag == "ul" and self._in_feature_bullets:
            self._bullets_depth -= 1
            if self._bullets_depth <= 0:
                self._in_feature_bullets = False

    def handle_data(self, data: str) -> None:
        if self._in_product_title:
            self._title_parts.append(data)
        elif self._in_bullet_span:
            self._bullet_parts.append(data)


def _extract_product_content(
    html: str,
    base_url: str,
    max_snippets: int = 5,
) -> tuple[list[str], list[str]]:
    """Parse an Amazon product page and return (absolute_links, text_snippets)."""
    parser = _AmazonProductParser()
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

    snippets: list[str] = []
    if parser.title:
        snippets.append(parser.title)
    snippets.extend(parser.bullets[:max_snippets - 1])

    return links, snippets[:max_snippets]


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class AmazonPlugin(SitePlugin):
    """
    Site plugin for Amazon product search.

    Searches amazon.com/s and parses product listings from the SERP HTML.
    Browses individual product pages to extract titles, prices, and feature
    bullets for TF-IDF topic expansion.

    Amazon's HTML is complex and changes frequently; the parser is designed
    to degrade gracefully rather than throw errors on unexpected structure.
    """

    @property
    def name(self) -> str:
        return "amazon"

    @property
    def domains(self) -> list[str]:
        return ["amazon.com", "www.amazon.com"]

    @property
    def preferred_transport(self) -> TransportType:
        # Amazon works with HTTP for basic searches; EITHER lets the scheduler
        # use a browser when Amazon's bot detection blocks the HTTP path.
        return TransportType.EITHER

    @property
    def rate_limit_rpm(self) -> int:
        # Amazon implements aggressive bot detection; 8 RPM keeps us well
        # within human-plausible interaction rates.
        return 8

    async def execute_search(
        self,
        context: SessionContext,
        transport,
    ) -> list[SearchResult]:
        """
        Search Amazon and return product listings.

        Fetches amazon.com/s?k=<query> and parses product result containers
        identified by data-component-type="s-search-result". Extracts titles,
        product page URLs, and price strings as snippets.

        Args:
            context: Session context providing the current query and fingerprint.
            transport: Active transport with .get(url, fingerprint) coroutine.

        Returns:
            Ordered list of SearchResult objects (position 1-indexed).
        """
        query = context.queries[context.current_query_index]
        encoded = quote_plus(query)
        url = f"https://www.amazon.com/s?k={encoded}"

        response = await transport.get(url, context.persona.fingerprint)

        parser = _AmazonSearchParser()
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
        Fetch an Amazon product page and extract details.

        Extracts the product title, feature bullets, and outbound links from
        the product detail page. Dwell time (15–90 seconds) reflects the range
        from quickly scanning a price to reading full product descriptions.

        Args:
            result: The SearchResult (product listing) to visit.
            context: Active session context for persona fingerprint.
            transport: Active transport exposing .get(url, fingerprint).

        Returns:
            BrowseAction recording the visit with product content as snippets.
        """
        response = await transport.get(result.url, context.persona.fingerprint)

        links, snippets = _extract_product_content(
            response.html,
            base_url=result.url,
            max_snippets=5,
        )

        # Amazon product pages range from quick price checks to deep reading
        dwell_time = random.uniform(15.0, 90.0)

        return BrowseAction(
            url_visited=result.url,
            dwell_time_s=dwell_time,
            links_found=links,
            content_snippets=snippets,
            status_code=response.status,
        )
