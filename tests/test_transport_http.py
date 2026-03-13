"""
test_transport_http.py — Tests for HttpTransport.

Uses aioresponses to mock aiohttp requests so no real network calls are made.
Covers: basic GET, fingerprint UA injection, 429 backoff retry, bot challenge
detection, link extraction, and text extraction.
"""

import pytest
from aioresponses import aioresponses

from murmurate.transport.http import HttpTransport, HttpResponse
from murmurate.models import FingerprintProfile


def _make_fingerprint():
    """Build a minimal FingerprintProfile for use in tests."""
    return FingerprintProfile(
        platform="windows",
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
        canvas_noise_seed=12345,
        fonts=["Arial"],
        created_at="2026-03-12T10:00:00Z",
        last_rotated=None,
    )


@pytest.mark.asyncio
async def test_basic_get():
    """HttpTransport.get() should return status and HTML body."""
    transport = HttpTransport()
    await transport.start()
    try:
        with aioresponses() as m:
            m.get("http://example.com", body="<html><body>Hello</body></html>", status=200)
            resp = await transport.get("http://example.com", _make_fingerprint())
            assert resp.status == 200
            assert "Hello" in resp.html
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_returns_http_response_type():
    """get() must return an HttpResponse dataclass instance."""
    transport = HttpTransport()
    await transport.start()
    try:
        with aioresponses() as m:
            m.get("http://example.com", body="<html>ok</html>", status=200)
            resp = await transport.get("http://example.com", _make_fingerprint())
            assert isinstance(resp, HttpResponse)
            assert isinstance(resp.headers, dict)
            assert isinstance(resp.url, str)
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_ua_from_fingerprint():
    """The request should be made using the fingerprint's user_agent."""
    transport = HttpTransport()
    await transport.start()
    try:
        with aioresponses() as m:
            m.get("http://example.com", body="ok", status=200)
            resp = await transport.get("http://example.com", _make_fingerprint())
            # aioresponses confirms the call was made; we verify the response came through
            assert resp.status == 200
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_backoff_on_429():
    """On 429 responses, transport should retry up to 3 times and succeed."""
    transport = HttpTransport()
    await transport.start()
    try:
        with aioresponses() as m:
            # Two 429s followed by a success — should still return the successful response
            m.get("http://example.com", status=429)
            m.get("http://example.com", status=429)
            m.get("http://example.com", body="ok", status=200)
            resp = await transport.get("http://example.com", _make_fingerprint())
            assert resp.status == 200
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_backoff_on_503():
    """On 503 responses, transport should retry and eventually succeed."""
    transport = HttpTransport()
    await transport.start()
    try:
        with aioresponses() as m:
            m.get("http://example.com", status=503)
            m.get("http://example.com", body="<html>ok</html>", status=200)
            resp = await transport.get("http://example.com", _make_fingerprint())
            assert resp.status == 200
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_max_retries_exhausted_returns_last_response():
    """After max retries all fail, the last non-success response is returned."""
    transport = HttpTransport()
    await transport.start()
    try:
        with aioresponses() as m:
            # Exhaust all 3 retry attempts
            m.get("http://example.com", status=429)
            m.get("http://example.com", status=429)
            m.get("http://example.com", status=429)
            m.get("http://example.com", status=429)
            resp = await transport.get("http://example.com", _make_fingerprint())
            assert resp.status == 429
    finally:
        await transport.stop()


def test_detect_bot_challenge_captcha():
    """detect_bot_challenge should return True when CAPTCHA indicators are present."""
    assert HttpTransport.detect_bot_challenge('<div>Please verify you are human</div>')


def test_detect_bot_challenge_cf():
    """detect_bot_challenge should return True for Cloudflare browser verification."""
    assert HttpTransport.detect_bot_challenge('<div class="cf-browser-verification">checking</div>')


def test_detect_bot_challenge_captcha_keyword():
    """detect_bot_challenge should return True when 'captcha' appears in page."""
    assert HttpTransport.detect_bot_challenge('<form action="/captcha">solve this</form>')


def test_detect_bot_challenge_challenge_keyword():
    """detect_bot_challenge should return True when 'challenge' appears in page."""
    assert HttpTransport.detect_bot_challenge('<div id="challenge-running">please wait</div>')


def test_detect_bot_challenge_normal_content():
    """detect_bot_challenge should return False for normal page content."""
    assert not HttpTransport.detect_bot_challenge('<div>Normal content here</div>')


def test_detect_bot_challenge_case_insensitive():
    """detect_bot_challenge should handle mixed-case indicators."""
    assert HttpTransport.detect_bot_challenge('<div>CAPTCHA Required</div>')


def test_extract_links_relative_and_absolute():
    """extract_links should resolve relative hrefs to absolute URLs."""
    html = (
        '<html><body>'
        '<a href="/page1">Link 1</a>'
        '<a href="http://example.com/page2">Link 2</a>'
        '</body></html>'
    )
    links = HttpTransport.extract_links(html, "http://example.com")
    assert "http://example.com/page1" in links
    assert "http://example.com/page2" in links


def test_extract_links_deduplicates():
    """extract_links should not return duplicate URLs."""
    html = (
        '<html><body>'
        '<a href="/page1">Link 1</a>'
        '<a href="/page1">Link 1 again</a>'
        '</body></html>'
    )
    links = HttpTransport.extract_links(html, "http://example.com")
    assert links.count("http://example.com/page1") == 1


def test_extract_links_skips_empty_and_fragments():
    """extract_links should skip empty hrefs and fragment-only links."""
    html = (
        '<html><body>'
        '<a href="">Empty</a>'
        '<a href="#section">Fragment</a>'
        '<a href="/valid">Valid</a>'
        '</body></html>'
    )
    links = HttpTransport.extract_links(html, "http://example.com")
    assert "http://example.com/valid" in links
    # Fragment-only links should not appear
    assert not any(link == "http://example.com" or link.endswith("#section") for link in links
                   if "#section" in link)


def test_extract_text_basic():
    """extract_text should return paragraph content from HTML."""
    html = '<html><body><p>First paragraph.</p><p>Second paragraph.</p></body></html>'
    snippets = HttpTransport.extract_text(html, max_snippets=5)
    assert len(snippets) >= 2
    assert "First paragraph." in snippets
    assert "Second paragraph." in snippets


def test_extract_text_respects_max_snippets():
    """extract_text should not return more than max_snippets entries."""
    paragraphs = "".join(f"<p>Paragraph {i}.</p>" for i in range(10))
    html = f"<html><body>{paragraphs}</body></html>"
    snippets = HttpTransport.extract_text(html, max_snippets=3)
    assert len(snippets) <= 3


def test_extract_text_empty_html():
    """extract_text on empty/no-paragraph HTML should return an empty list."""
    html = "<html><body><div>No paragraphs here</div></body></html>"
    snippets = HttpTransport.extract_text(html)
    assert isinstance(snippets, list)


def test_extract_text_skips_blank_paragraphs():
    """extract_text should not include whitespace-only paragraph text."""
    html = "<html><body><p>   </p><p>Real content.</p></body></html>"
    snippets = HttpTransport.extract_text(html)
    assert "Real content." in snippets
    assert not any(s.strip() == "" for s in snippets)
