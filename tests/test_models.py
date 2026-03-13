"""
test_models.py — Unit tests for the core data models.

These tests verify that all dataclasses can be instantiated correctly and
that their fields behave as expected (defaults, mutability, enum values).
No I/O or async operations are needed here — pure in-memory construction.
"""

import pytest
from murmurate.models import (
    BrowseAction,
    BrowsingSession,
    FingerprintProfile,
    PersonaState,
    SearchResult,
    SessionContext,
    SessionResult,
    TopicNode,
    TransportType,
)


# ---------------------------------------------------------------------------
# Helpers — reusable minimal instances
# ---------------------------------------------------------------------------

def make_fingerprint() -> FingerprintProfile:
    """Return a minimal but fully-specified FingerprintProfile."""
    return FingerprintProfile(
        platform="Win32",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        screen_width=1920,
        screen_height=1080,
        viewport_width=1280,
        viewport_height=800,
        timezone_id="America/Chicago",
        locale="en-US",
        accept_language="en-US,en;q=0.9",
        hardware_concurrency=8,
        device_memory=8,
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer="ANGLE (NVIDIA, GeForce GTX 1060)",
        canvas_noise_seed=42,
        fonts=["Arial", "Times New Roman", "Courier New"],
        created_at="2026-01-01T00:00:00Z",
    )


def make_topic_node(topic: str = "linux kernel", depth: int = 0) -> TopicNode:
    """Return a minimal TopicNode."""
    return TopicNode(topic=topic, depth=depth)


def make_persona(name: str = "alice") -> PersonaState:
    """Return a minimal PersonaState with a fingerprint and one seed topic."""
    return PersonaState(
        name=name,
        version=1,
        seeds=["linux", "open source"],
        topic_tree=[make_topic_node()],
        fingerprint=make_fingerprint(),
        created_at="2026-01-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# TransportType enum
# ---------------------------------------------------------------------------

class TestTransportType:
    def test_http_value(self):
        assert TransportType.HTTP.value == "http"

    def test_browser_value(self):
        assert TransportType.BROWSER.value == "browser"

    def test_either_value(self):
        assert TransportType.EITHER.value == "either"

    def test_enum_members_count(self):
        """Ensure no extra values were accidentally added."""
        assert len(TransportType) == 3

    def test_lookup_by_value(self):
        assert TransportType("http") is TransportType.HTTP
        assert TransportType("browser") is TransportType.BROWSER
        assert TransportType("either") is TransportType.EITHER


# ---------------------------------------------------------------------------
# TopicNode
# ---------------------------------------------------------------------------

class TestTopicNode:
    def test_basic_creation(self):
        node = TopicNode(topic="python", depth=0)
        assert node.topic == "python"
        assert node.depth == 0

    def test_default_children_is_empty_list(self):
        node = TopicNode(topic="python", depth=0)
        assert node.children == []

    def test_default_mutable_fields_are_independent(self):
        """Each instance must get its own list — not share a single default."""
        node_a = TopicNode(topic="a", depth=0)
        node_b = TopicNode(topic="b", depth=0)
        node_a.children.append(TopicNode(topic="child", depth=1))
        assert node_b.children == [], "Mutable default not isolated between instances"

    def test_add_child(self):
        parent = TopicNode(topic="programming", depth=0)
        child = TopicNode(topic="python", depth=1)
        parent.children.append(child)
        assert len(parent.children) == 1
        assert parent.children[0].topic == "python"

    def test_add_multiple_children(self):
        parent = TopicNode(topic="programming", depth=0)
        for lang in ["python", "rust", "go"]:
            parent.children.append(TopicNode(topic=lang, depth=1))
        assert len(parent.children) == 3

    def test_nested_children(self):
        """Verify the tree can nest at arbitrary depth."""
        root = TopicNode(topic="tech", depth=0)
        mid = TopicNode(topic="linux", depth=1)
        leaf = TopicNode(topic="kernel", depth=2)
        mid.children.append(leaf)
        root.children.append(mid)
        assert root.children[0].children[0].topic == "kernel"

    def test_query_count_default(self):
        node = TopicNode(topic="test", depth=0)
        assert node.query_count == 0

    def test_last_used_default_is_none(self):
        node = TopicNode(topic="test", depth=0)
        assert node.last_used is None

    def test_last_used_can_be_set(self):
        node = TopicNode(topic="test", depth=0)
        node.last_used = "2026-01-15T12:00:00Z"
        assert node.last_used == "2026-01-15T12:00:00Z"


# ---------------------------------------------------------------------------
# FingerprintProfile
# ---------------------------------------------------------------------------

class TestFingerprintProfile:
    def test_creation_with_all_fields(self):
        fp = make_fingerprint()
        assert fp.platform == "Win32"
        assert fp.screen_width == 1920
        assert fp.screen_height == 1080
        assert fp.viewport_width == 1280
        assert fp.viewport_height == 800
        assert fp.hardware_concurrency == 8
        assert fp.device_memory == 8
        assert fp.canvas_noise_seed == 42
        assert fp.locale == "en-US"

    def test_fonts_is_list(self):
        fp = make_fingerprint()
        assert isinstance(fp.fonts, list)
        assert "Arial" in fp.fonts

    def test_last_rotated_default_is_none(self):
        fp = make_fingerprint()
        assert fp.last_rotated is None

    def test_last_rotated_can_be_set(self):
        fp = make_fingerprint()
        fp.last_rotated = "2026-06-01T00:00:00Z"
        assert fp.last_rotated == "2026-06-01T00:00:00Z"

    def test_webgl_fields(self):
        fp = make_fingerprint()
        assert "NVIDIA" in fp.webgl_vendor
        assert "ANGLE" in fp.webgl_renderer


# ---------------------------------------------------------------------------
# PersonaState
# ---------------------------------------------------------------------------

class TestPersonaState:
    def test_creation(self):
        persona = make_persona()
        assert persona.name == "alice"
        assert persona.version == 1
        assert persona.seeds == ["linux", "open source"]
        assert persona.created_at == "2026-01-01T00:00:00Z"

    def test_default_total_sessions(self):
        persona = make_persona()
        assert persona.total_sessions == 0

    def test_default_expertise_level(self):
        persona = make_persona()
        assert persona.expertise_level == 0.0

    def test_fingerprint_attached(self):
        persona = make_persona()
        assert isinstance(persona.fingerprint, FingerprintProfile)
        assert persona.fingerprint.platform == "Win32"

    def test_topic_tree_attached(self):
        persona = make_persona()
        assert len(persona.topic_tree) == 1
        assert persona.topic_tree[0].topic == "linux kernel"

    def test_expertise_level_update(self):
        persona = make_persona()
        persona.expertise_level = 0.75
        assert persona.expertise_level == 0.75

    def test_version_increment(self):
        persona = make_persona()
        persona.version += 1
        assert persona.version == 2


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------

class TestSearchResult:
    def test_creation(self):
        result = SearchResult(
            title="Linux Kernel Documentation",
            url="https://www.kernel.org/doc/html/latest/",
            snippet="Official Linux kernel docs covering subsystems and APIs.",
            position=1,
        )
        assert result.title == "Linux Kernel Documentation"
        assert result.url == "https://www.kernel.org/doc/html/latest/"
        assert result.position == 1

    def test_position_ordering(self):
        """position is 1-indexed; verify we can store positions correctly."""
        results = [
            SearchResult(title=f"Result {i}", url=f"https://example.com/{i}",
                         snippet="...", position=i)
            for i in range(1, 6)
        ]
        assert results[0].position == 1
        assert results[4].position == 5

    def test_snippet_stored(self):
        result = SearchResult(
            title="Test", url="https://example.com", snippet="A useful snippet.", position=3
        )
        assert result.snippet == "A useful snippet."


# ---------------------------------------------------------------------------
# SessionResult
# ---------------------------------------------------------------------------

class TestSessionResult:
    def test_creation(self):
        sr = SessionResult(
            session_id="abc-123",
            persona_name="alice",
            plugin_name="google-http",
            transport_type=TransportType.HTTP,
            queries_executed=5,
            results_browsed=12,
            total_duration_s=47.3,
            new_subtopics=["kernel modules", "device drivers"],
            errors=[],
            completed_at="2026-01-15T13:00:00Z",
            machine_id="roguenode",
        )
        assert sr.session_id == "abc-123"
        assert sr.persona_name == "alice"
        assert sr.queries_executed == 5
        assert sr.results_browsed == 12
        assert sr.total_duration_s == 47.3
        assert sr.transport_type == TransportType.HTTP
        assert sr.machine_id == "roguenode"

    def test_new_subtopics_list(self):
        sr = SessionResult(
            session_id="xyz-456",
            persona_name="bob",
            plugin_name="bing-http",
            transport_type=TransportType.HTTP,
            queries_executed=3,
            results_browsed=7,
            total_duration_s=30.0,
            new_subtopics=["rust async", "tokio runtime"],
            errors=[],
            completed_at="2026-01-15T14:00:00Z",
            machine_id="roguenode",
        )
        assert "rust async" in sr.new_subtopics
        assert len(sr.new_subtopics) == 2

    def test_errors_list(self):
        sr = SessionResult(
            session_id="err-789",
            persona_name="carol",
            plugin_name="ddg-browser",
            transport_type=TransportType.BROWSER,
            queries_executed=2,
            results_browsed=3,
            total_duration_s=25.5,
            new_subtopics=[],
            errors=["Timeout on https://example.com", "HTTP 503 on https://other.com"],
            completed_at="2026-01-15T15:00:00Z",
            machine_id="roguenode",
        )
        assert len(sr.errors) == 2
        assert "Timeout" in sr.errors[0]

    def test_transport_type_browser(self):
        sr = SessionResult(
            session_id="br-001",
            persona_name="dave",
            plugin_name="google-browser",
            transport_type=TransportType.BROWSER,
            queries_executed=4,
            results_browsed=8,
            total_duration_s=60.0,
            new_subtopics=[],
            errors=[],
            completed_at="2026-01-15T16:00:00Z",
            machine_id="roguenode",
        )
        assert sr.transport_type == TransportType.BROWSER
