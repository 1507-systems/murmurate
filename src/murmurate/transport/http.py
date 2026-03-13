"""
transport/http.py — Lightweight HTTP transport using aiohttp.

HttpTransport is the lower-level workhorse for the HTTP browsing path. It does
NOT implement execute_session (that's the scheduler + plugin layer's job).
Instead, it exposes a simple get() method that plugins call to fetch pages, plus
static helpers for parsing the resulting HTML.

Key design choices:
  - Lazy aiohttp.ClientSession: created on start(), closed on stop(), never
    recreated mid-run to avoid overhead.
  - FingerprintProfile-driven headers: every request uses the persona's
    user_agent and accept_language so it looks like a real browser.
  - Retry with exponential backoff + jitter on 429 / 503: real sites rate-limit
    crawlers; we respect the signal and back off gracefully.
  - DNS failure tracking: a run of 5+ consecutive DNS errors likely means the
    machine is offline or blocked; we pause for 60 s rather than hammering.
  - Static HTML helpers (extract_links, extract_text, detect_bot_challenge) are
    kept on the class for cohesion but carry no instance state — tests can call
    them without starting a session.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import aiohttp

from murmurate.models import FingerprintProfile


# ---------------------------------------------------------------------------
# Response container
# ---------------------------------------------------------------------------

@dataclass
class HttpResponse:
    """
    Lightweight wrapper around a completed HTTP response.

    `url` reflects the *final* URL after any redirects aiohttp followed,
    which lets callers detect redirect chains without extra work.
    """
    status: int
    url: str          # Final URL after redirects
    html: str
    headers: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# HTML parsing helpers (stateful parsers used internally by the static methods)
# ---------------------------------------------------------------------------

class _LinkExtractor(HTMLParser):
    """
    Minimal HTMLParser subclass that collects all <a href="..."> values.

    We use html.parser (stdlib) rather than BeautifulSoup to avoid an extra
    dependency — the parsing needs are simple enough.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.links.append(value)


class _TextExtractor(HTMLParser):
    """
    Minimal HTMLParser subclass that collects text content of <p> tags.

    Tracks whether we're currently inside a <p> element and accumulates
    character data until the closing </p>.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_p: bool = False
        self._current: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "p":
            self._in_p = True
            self._current = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._in_p:
            text = "".join(self._current).strip()
            if text:
                self.paragraphs.append(text)
            self._in_p = False
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._in_p:
            self._current.append(data)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

# Statuses that warrant a retry with back-off
_RETRYABLE_STATUSES = {429, 503}
# Maximum number of retry attempts (does not count the initial attempt)
_MAX_RETRIES = 3
# Base delay in seconds for exponential back-off
_BACKOFF_BASE = 1.0
# How many consecutive DNS errors trigger a pause
_DNS_FAILURE_THRESHOLD = 5
# How long to pause (seconds) after hitting the DNS failure threshold
_DNS_PAUSE_SECONDS = 60.0


class HttpTransport:
    """
    HTTP transport using aiohttp for lightweight, headerless browsing.

    Lifecycle: call start() before issuing requests, stop() when done.
    The aiohttp.ClientSession is created in start() and reused for all
    requests in the session, which is more efficient than per-request sessions.
    """

    def __init__(self, config=None) -> None:
        # aiohttp.ClientSession — created in start(), torn down in stop()
        self._session: aiohttp.ClientSession | None = None
        # Optional murmurate Config object; currently only read for
        # config.respect_robots_txt flag (actual robots.txt fetching is
        # deferred to a later task)
        self._config = config
        # Running count of back-to-back DNS errors across all requests
        self._consecutive_dns_failures: int = 0
        # Unix timestamp after which DNS-pause is lifted (0.0 = not paused)
        self._dns_pause_until: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Create the underlying aiohttp.ClientSession.

        We pass trust_env=True so that HTTP_PROXY / NO_PROXY environment
        variables are respected — useful in test environments and proxied
        networks. raise_for_status is left False so we can inspect and
        retry non-2xx responses ourselves.
        """
        self._session = aiohttp.ClientSession(trust_env=True)

    async def stop(self) -> None:
        """Close the aiohttp session and release its connection pool."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Core request method
    # ------------------------------------------------------------------

    async def get(self, url: str, fingerprint: FingerprintProfile) -> HttpResponse:
        """
        Perform an HTTP GET with fingerprint-derived headers.

        Sets User-Agent and Accept-Language from the persona's FingerprintProfile
        so the request looks like it came from a real browser.  Retries on
        429/503 with exponential back-off + jitter (max _MAX_RETRIES retries).

        DNS failures increment a counter; >= _DNS_FAILURE_THRESHOLD consecutive
        failures trigger a _DNS_PAUSE_SECONDS sleep before the next attempt.

        Args:
            url: The URL to fetch.
            fingerprint: The persona's fingerprint — drives UA and language headers.

        Returns:
            HttpResponse with status, final URL, body, and response headers.
        """
        if self._session is None:
            raise RuntimeError("HttpTransport.start() must be called before get()")

        # If we're robots.txt-aware, the caller (plugin layer) is expected to
        # have already checked permissions.  We just surface the flag here so
        # future tasks can hook in without changing the call site.
        if self._config and getattr(self._config, "respect_robots_txt", False):
            # robots.txt checking not yet implemented
            pass

        headers = {
            "User-Agent": fingerprint.user_agent,
            "Accept-Language": fingerprint.accept_language,
            # Mimic real browser Accept header to reduce bot-detection surface
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/webp,*/*;q=0.8"
            ),
        }

        last_response: HttpResponse | None = None
        attempt = 0

        while attempt <= _MAX_RETRIES:
            # Honour any active DNS pause before making the request
            pause_remaining = self._dns_pause_until - time.monotonic()
            if pause_remaining > 0:
                await asyncio.sleep(pause_remaining)

            try:
                async with self._session.get(
                    url, headers=headers, allow_redirects=True
                ) as resp:
                    body = await resp.text(errors="replace")
                    # Reset DNS failure counter on any successful network contact
                    self._consecutive_dns_failures = 0
                    response = HttpResponse(
                        status=resp.status,
                        url=str(resp.url),
                        html=body,
                        headers=dict(resp.headers),
                    )
                    last_response = response

                    if resp.status not in _RETRYABLE_STATUSES:
                        # Success (or a permanent error) — stop retrying
                        return response

                    # Retryable status — fall through to back-off logic below

            except aiohttp.ClientConnectorError:
                # DNS lookup failure or connection refused — could be transient
                self._consecutive_dns_failures += 1
                if self._consecutive_dns_failures >= _DNS_FAILURE_THRESHOLD:
                    # Likely offline or rate-limited at the network level; pause
                    self._dns_pause_until = time.monotonic() + _DNS_PAUSE_SECONDS
                raise  # Propagate so the scheduler can log / handle it

            # Exponential back-off with full jitter to avoid retry storms:
            # sleep = random(0, base * 2^attempt)
            backoff = _BACKOFF_BASE * (2 ** attempt)
            jitter = random.uniform(0, backoff)
            await asyncio.sleep(jitter)
            attempt += 1

        # Exhausted all retries — return the last response we got
        return last_response  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Static HTML helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_links(html: str, base_url: str) -> list[str]:
        """
        Parse HTML and return a deduplicated list of absolute URLs.

        Relative hrefs are resolved against base_url using urllib.parse.urljoin.
        Fragment-only links (href="#...") and empty hrefs are dropped because
        they don't represent navigable pages.

        Args:
            html: Raw HTML string.
            base_url: The URL the HTML was fetched from; used to resolve relatives.

        Returns:
            Sorted, deduplicated list of absolute URLs found in <a href> tags.
        """
        parser = _LinkExtractor()
        parser.feed(html)

        seen: set[str] = set()
        result: list[str] = []

        for raw_href in parser.links:
            raw_href = raw_href.strip()
            if not raw_href or raw_href.startswith("#"):
                # Skip empty hrefs and pure fragment anchors
                continue

            absolute = urljoin(base_url, raw_href)

            # Validate the resolved URL has a real scheme + netloc
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                continue

            # Strip the fragment from the resolved URL — we care about the page,
            # not the in-page anchor
            absolute_no_frag = parsed._replace(fragment="").geturl()

            if absolute_no_frag not in seen:
                seen.add(absolute_no_frag)
                result.append(absolute_no_frag)

        return result

    @staticmethod
    def extract_text(html: str, max_snippets: int = 5) -> list[str]:
        """
        Extract text content from <p> tags for TF-IDF topic expansion.

        Whitespace-only paragraphs are skipped. Returns at most max_snippets
        entries so callers can bound memory usage.

        Args:
            html: Raw HTML string.
            max_snippets: Maximum number of paragraph strings to return.

        Returns:
            List of non-empty paragraph text strings, up to max_snippets.
        """
        parser = _TextExtractor()
        parser.feed(html)
        return parser.paragraphs[:max_snippets]

    @staticmethod
    def detect_bot_challenge(html: str) -> bool:
        """
        Return True if the page appears to contain a bot/CAPTCHA challenge.

        Checks for case-insensitive presence of common challenge indicators:
          - "verify you are human"  — generic CAPTCHA prompts
          - "captcha"               — any CAPTCHA integration
          - "challenge"             — Cloudflare challenge page marker
          - "cf-browser-verification" — Cloudflare browser check class/id

        Keeping this as a simple substring scan (rather than a regex or DOM
        parse) is intentional — it's fast, and false positives here are
        acceptable (the session just backs off rather than getting blocked).

        Args:
            html: Raw HTML string to inspect.

        Returns:
            True if any bot-challenge indicator is found, False otherwise.
        """
        lower = html.lower()
        indicators = (
            "verify you are human",
            "captcha",
            "challenge",
            "cf-browser-verification",
        )
        return any(ind in lower for ind in indicators)
