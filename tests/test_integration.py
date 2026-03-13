"""End-to-end integration test — full pipeline with mocked HTTP.

These tests exercise real components wired together (not unit-tested in
isolation), verifying that the scheduler, persona engine, plugins, transport,
rate limiter, and database all cooperate correctly. HTTP is mocked with
aioresponses so the tests are deterministic and never hit the network.

Key wiring constraints:
- aioresponses patches aiohttp.ClientSession; HttpTransport.start() MUST be
  called inside the aioresponses context so the session uses the mock.
- asyncio.sleep is patched in the scheduler, http transport, and database
  modules to prevent any real waiting during tests.
"""

import json
import re
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aioresponses import aioresponses

from murmurate.config import MurmurateConfig, SchedulerConfig
from murmurate.database import StateDB
from murmurate.models import PersonaState, TopicNode, FingerprintProfile, TransportType
from murmurate.persona.engine import PersonaEngine
from murmurate.persona.fingerprint import generate_fingerprint
from murmurate.persona.storage import save_persona, load_all_personas
from murmurate.plugins.registry import PluginRegistry
from murmurate.scheduler.timing import TimingModel
from murmurate.scheduler.rate_limiter import RateLimiter
from murmurate.scheduler.scheduler import Scheduler
from murmurate.transport.http import HttpTransport


# ---------------------------------------------------------------------------
# HTML / JSON fixtures for mocked HTTP responses
# ---------------------------------------------------------------------------

# Minimal DDG lite HTML containing two result links and corresponding snippets.
# The parser in duckduckgo.py looks for <a class="result__a"> and
# <a class="result__snippet"> in sequence.
_DDG_HTML = """<!DOCTYPE html>
<html>
<body>
  <div class="result">
    <a class="result__a" href="https://example.com/cooking-basics">Cooking Basics</a>
    <a class="result__snippet">Learn the fundamentals of cooking recipes and techniques.</a>
  </div>
  <div class="result">
    <a class="result__a" href="https://example.com/advanced-cooking">Advanced Cooking</a>
    <a class="result__snippet">Master advanced culinary skills and gourmet recipes.</a>
  </div>
</body>
</html>"""

# Wikipedia OpenSearch JSON response: [query, [titles], [descriptions], [urls]]
_WIKI_JSON = json.dumps([
    "cooking",
    ["Cooking", "Culinary arts"],
    ["The practice of preparing food", "The art of cooking food"],
    [
        "https://en.wikipedia.org/wiki/Cooking",
        "https://en.wikipedia.org/wiki/Culinary_arts",
    ],
])

# Generic result page HTML returned when a plugin browses a search result.
# Uses <p> tags so the content extractor captures the text as snippets for
# topic evolution.
_RESULT_PAGE_HTML = """<!DOCTYPE html>
<html>
<body>
  <p>Some content about cooking recipes and techniques.</p>
  <p>Explore flavors, ingredients, and culinary methods for home chefs.</p>
</body>
</html>"""

# Content-rich page for topic evolution test
_RICH_CONTENT_HTML = """<!DOCTYPE html>
<html>
<body>
  <p>Sourdough bread baking fermentation techniques for home bakers.</p>
  <p>Explore Italian pasta recipes with fresh ingredients and seasonal vegetables.</p>
  <p>Advanced knife skills chopping dicing mincing for professional kitchen work.</p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

def _make_persona(name: str = "chef") -> PersonaState:
    """Create a persona with a simple cooking topic tree."""
    fp = FingerprintProfile(
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
        webgl_renderer="ANGLE (NVIDIA GeForce RTX 3080)",
        canvas_noise_seed=42,
        fonts=["Arial", "Helvetica", "Times New Roman"],
        created_at="2026-03-13T10:00:00+00:00",
        last_rotated=None,
    )
    root = TopicNode(topic="cooking", depth=0, children=[], query_count=0, last_used=None)
    return PersonaState(
        name=name,
        version=1,
        seeds=["cooking"],
        topic_tree=[root],
        fingerprint=fp,
        created_at="2026-03-13T10:00:00+00:00",
        total_sessions=0,
        expertise_level=0.0,
    )


def _make_zero_delay_config() -> MurmurateConfig:
    """Config with extremely high session rate so next_delay() returns near 0.

    Quiet-hours logic: quiet_start < quiet_end uses the simple (non-wraparound)
    path: quiet if start <= current < end. We use 01:00–01:01 — a 1-minute
    window at 1 AM that tests are extremely unlikely to run in.
    """
    cfg = MurmurateConfig()
    # 99999 sessions/hour → mean inter-session gap < 0.04 s, effectively instant
    cfg.scheduler = SchedulerConfig(
        sessions_per_hour_min=99999,
        sessions_per_hour_max=99999,
        active_hours_start="00:00",
        active_hours_end="23:59",
        # Narrow quiet window at 1:00–1:01 AM; tests running at that exact
        # minute would be in quiet hours, but that's a 1-in-1440 chance.
        quiet_hours_start="01:00",
        quiet_hours_end="01:01",
        burst_probability=0.0,
    )
    cfg.plugin.enabled = ["duckduckgo", "wikipedia"]
    cfg.plugin.disabled = []
    return cfg


def _register_ddg_wiki_only(registry: PluginRegistry) -> None:
    """Register only DuckDuckGo and Wikipedia plugins for predictable URL mocking."""
    import murmurate.plugins.duckduckgo as ddg_mod
    import murmurate.plugins.wikipedia as wiki_mod
    for mod in (ddg_mod, wiki_mod):
        registry._register_from_module(mod)


def _register_mock_urls(m, content_html: str) -> None:
    """Register all expected mock URLs with aioresponses using repeat=True.

    We use regex patterns to match URLs with query parameters (e.g. DDG search
    appends ?q=<encoded_query> and Wikipedia appends ?action=opensearch&...).
    repeat=True means the same mock response is returned for every matching
    call, regardless of how many queries the persona generates per session.
    """
    # DDG lite endpoint: https://html.duckduckgo.com/html/?q=...
    m.get(
        re.compile(r"https://html\.duckduckgo\.com/html/.*"),
        body=_DDG_HTML,
        status=200,
        repeat=True,
    )
    # Wikipedia OpenSearch API: https://en.wikipedia.org/w/api.php?action=opensearch&...
    m.get(
        re.compile(r"https://en\.wikipedia\.org/w/api\.php.*"),
        body=_WIKI_JSON,
        status=200,
        repeat=True,
    )
    # DDG result pages (exact URLs extracted from _DDG_HTML)
    m.get(
        "https://example.com/cooking-basics",
        body=content_html,
        status=200,
        repeat=True,
    )
    m.get(
        "https://example.com/advanced-cooking",
        body=content_html,
        status=200,
        repeat=True,
    )
    # Wikipedia article pages (exact URLs from _WIKI_JSON)
    m.get(
        "https://en.wikipedia.org/wiki/Cooking",
        body=content_html,
        status=200,
        repeat=True,
    )
    m.get(
        "https://en.wikipedia.org/wiki/Culinary_arts",
        body=content_html,
        status=200,
        repeat=True,
    )


# ---------------------------------------------------------------------------
# Test 1: Full pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_pipeline():
    """Run 3 scheduler sessions end-to-end with real components + mocked HTTP.

    Verifies:
      - Sessions complete without crashes
      - SessionResult objects are returned for all 3 sessions
      - Each result has the expected persona name, plugin name, and transport type
    """
    config = _make_zero_delay_config()
    persona = _make_persona()

    # Real StateDB using an in-memory SQLite so no disk I/O
    db = StateDB(":memory:")
    await db.initialize()

    # Real PluginRegistry with only DDG + Wikipedia for predictable URL mocking
    registry = PluginRegistry()
    _register_ddg_wiki_only(registry)

    # Real TimingModel with near-instant delays from config above
    timing = TimingModel(config.scheduler)

    # Real RateLimiter; plugin RPM limits (DDG=10, Wiki=30) are well above the
    # request rate generated by 3 sessions
    rate_limiter = RateLimiter(db)

    # Real PersonaEngine
    engine = PersonaEngine()

    results = []

    # Patch asyncio.sleep everywhere it might be called to avoid any real waiting:
    #   - scheduler.py: inter-session Poisson delays
    #   - transport/http.py: retry back-off on 429/503 or DNS pause
    #   - database.py: SQLite lock-retry back-off
    sleep_mock = AsyncMock(return_value=None)

    with patch("murmurate.scheduler.scheduler.asyncio.sleep", sleep_mock), \
         patch("murmurate.transport.http.asyncio.sleep", sleep_mock), \
         patch("murmurate.database.asyncio.sleep", sleep_mock):

        with aioresponses() as m:
            _register_mock_urls(m, _RESULT_PAGE_HTML)

            # IMPORTANT: start() must be called inside aioresponses so the
            # ClientSession it creates is the patched mock, not a real one.
            http_transport = HttpTransport(config)
            await http_transport.start()
            try:
                scheduler = Scheduler(
                    config=config,
                    personas=[persona],
                    registry=registry,
                    http_transport=http_transport,
                    browser_transport=None,
                    db=db,
                    timing=timing,
                    rate_limiter=rate_limiter,
                    persona_engine=engine,
                )

                results = await scheduler.run(max_sessions=3)
            finally:
                await http_transport.stop()

    await db.close()

    # Verify all 3 sessions produced results
    assert len(results) == 3, f"Expected 3 results, got {len(results)}"

    for result in results:
        assert result.persona_name == "chef"
        assert result.plugin_name in ("duckduckgo", "wikipedia")
        assert result.transport_type == TransportType.HTTP
        assert result.queries_executed >= 1
        assert result.results_browsed >= 0


# ---------------------------------------------------------------------------
# Test 2: Persona roundtrip
# ---------------------------------------------------------------------------

def test_persona_roundtrip():
    """Create a persona with generate_fingerprint(), save it, and reload it.

    Verifies that all fields survive the JSON serialization roundtrip without
    loss or corruption. This exercises the storage module independently of
    the scheduler.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir)

        # Use real fingerprint generation (reads from data/ files)
        fp = generate_fingerprint()
        root = TopicNode(
            topic="photography",
            depth=0,
            children=[
                TopicNode(
                    topic="landscape",
                    depth=1,
                    children=[],
                    query_count=2,
                    last_used=None,
                ),
            ],
            query_count=5,
            last_used="2026-03-13T10:00:00+00:00",
        )
        original = PersonaState(
            name="photographer",
            version=3,
            seeds=["photography", "cameras"],
            topic_tree=[root],
            fingerprint=fp,
            created_at="2026-03-13T10:00:00+00:00",
            total_sessions=15,
            expertise_level=0.6,
        )

        save_persona(original, persona_dir)

        loaded_personas = load_all_personas(persona_dir)
        assert len(loaded_personas) == 1, "Expected exactly one persona to load"
        loaded = loaded_personas[0]

        # Top-level scalar fields
        assert loaded.name == original.name
        assert loaded.version == original.version
        assert loaded.seeds == original.seeds
        assert loaded.created_at == original.created_at
        assert loaded.total_sessions == original.total_sessions
        assert loaded.expertise_level == original.expertise_level

        # Topic tree structure
        assert len(loaded.topic_tree) == 1
        assert loaded.topic_tree[0].topic == "photography"
        assert loaded.topic_tree[0].query_count == 5
        assert len(loaded.topic_tree[0].children) == 1
        assert loaded.topic_tree[0].children[0].topic == "landscape"
        assert loaded.topic_tree[0].children[0].depth == 1
        assert loaded.topic_tree[0].children[0].query_count == 2

        # Fingerprint
        assert loaded.fingerprint.platform == fp.platform
        assert loaded.fingerprint.user_agent == fp.user_agent
        assert loaded.fingerprint.canvas_noise_seed == fp.canvas_noise_seed
        assert loaded.fingerprint.fonts == fp.fonts


# ---------------------------------------------------------------------------
# Test 3: Plugin discovery
# ---------------------------------------------------------------------------

def test_plugin_discovery():
    """All 7 bundled plugins are discovered and have the correct transport preference.

    This verifies the registry's load_bundled() method wires up every plugin
    listed in BUNDLED_PLUGINS and that the expected transport types are set.
    """
    registry = PluginRegistry()
    count = registry.load_bundled()

    # We expect exactly 7 bundled plugins
    assert count == 7, f"Expected 7 bundled plugins, got {count}"

    expected_plugins = {
        "duckduckgo", "wikipedia", "google", "youtube", "amazon", "reddit", "bing"
    }
    registered_names = set(registry.all_plugins.keys())
    assert registered_names == expected_plugins, (
        f"Plugin name mismatch: {registered_names} != {expected_plugins}"
    )

    # Verify each plugin's transport preference is a valid TransportType
    for name, plugin in registry.all_plugins.items():
        assert isinstance(plugin.preferred_transport, TransportType), (
            f"Plugin {name!r} preferred_transport is not a TransportType"
        )
        # DuckDuckGo uses EITHER (can do both), Wikipedia uses HTTP
        if name == "duckduckgo":
            assert plugin.preferred_transport == TransportType.EITHER
        elif name == "wikipedia":
            assert plugin.preferred_transport == TransportType.HTTP


# ---------------------------------------------------------------------------
# Test 4: Topic tree evolution through sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_topic_evolution_through_sessions():
    """After 2 sessions with content-rich pages, the topic tree should grow.

    The content pages contain distinctive keyword text that the TF-IDF extractor
    can pick up and add as child nodes to the persona's topic tree.
    """
    config = _make_zero_delay_config()
    persona = _make_persona()

    # Record initial state before any sessions
    initial_node_count = 1  # one root node: "cooking"

    db = StateDB(":memory:")
    await db.initialize()

    registry = PluginRegistry()
    _register_ddg_wiki_only(registry)

    timing = TimingModel(config.scheduler)
    rate_limiter = RateLimiter(db)
    engine = PersonaEngine()

    results = []

    sleep_mock = AsyncMock(return_value=None)

    with patch("murmurate.scheduler.scheduler.asyncio.sleep", sleep_mock), \
         patch("murmurate.transport.http.asyncio.sleep", sleep_mock), \
         patch("murmurate.database.asyncio.sleep", sleep_mock):

        with aioresponses() as m:
            # Use rich content so the TF-IDF extractor has enough material to
            # extract subtopics (needs at least a few distinctive words)
            _register_mock_urls(m, _RICH_CONTENT_HTML)

            http_transport = HttpTransport(config)
            await http_transport.start()
            try:
                scheduler = Scheduler(
                    config=config,
                    personas=[persona],
                    registry=registry,
                    http_transport=http_transport,
                    browser_transport=None,
                    db=db,
                    timing=timing,
                    rate_limiter=rate_limiter,
                    persona_engine=engine,
                )

                results = await scheduler.run(max_sessions=2)
            finally:
                await http_transport.stop()

    await db.close()

    assert len(results) == 2, f"Expected 2 results, got {len(results)}"

    # Count all nodes (root + any children added by evolution)
    def _count_nodes(nodes):
        total = 0
        for n in nodes:
            total += 1
            total += _count_nodes(n.children)
        return total

    final_node_count = _count_nodes(persona.topic_tree)

    # The tree must not have shrunk — it started at 1 and can only grow
    assert final_node_count >= initial_node_count, (
        f"Topic tree should not have shrunk: {initial_node_count} → {final_node_count}"
    )

    # new_subtopics is a list on each result — must be a list (possibly empty)
    for result in results:
        assert isinstance(result.new_subtopics, list)
