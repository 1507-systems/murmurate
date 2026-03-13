"""
test_persona_storage.py — Tests for PersonaState JSON serialization/deserialization.

Tests follow TDD order: define expected behavior, then verify the implementation
matches. Each test is independent and uses tmp_path for filesystem isolation.
"""

import json
import logging
from pathlib import Path

import pytest

from murmurate.models import FingerprintProfile, PersonaState, TopicNode
from murmurate.persona.storage import load_all_personas, load_persona, save_persona


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def make_fingerprint() -> FingerprintProfile:
    """Return a minimal but complete FingerprintProfile for use in tests."""
    return FingerprintProfile(
        platform="Win32",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        screen_width=1920,
        screen_height=1080,
        viewport_width=1280,
        viewport_height=720,
        timezone_id="America/Chicago",
        locale="en-US",
        accept_language="en-US,en;q=0.9",
        hardware_concurrency=8,
        device_memory=8,
        webgl_vendor="Google Inc.",
        webgl_renderer="ANGLE (Intel, Mesa Intel)",
        canvas_noise_seed=42,
        fonts=["Arial", "Georgia"],
        created_at="2026-03-12T10:00:00Z",
        last_rotated=None,
    )


def make_persona(name: str = "woodworker") -> PersonaState:
    """Return a PersonaState with a simple two-level topic tree."""
    child = TopicNode(
        topic="hand tools",
        depth=1,
        query_count=5,
        last_used="2026-03-12T13:00:00Z",
        children=[],
    )
    root = TopicNode(
        topic="woodworking",
        depth=0,
        query_count=12,
        last_used="2026-03-12T14:30:00Z",
        children=[child],
    )
    return PersonaState(
        name=name,
        version=1,
        seeds=["woodworking"],
        topic_tree=[root],
        fingerprint=make_fingerprint(),
        created_at="2026-03-12T10:00:00Z",
        total_sessions=47,
        expertise_level=0.6,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_save_and_load_persona(tmp_path: Path) -> None:
    """Round-trip: save a PersonaState then load it back and verify equality."""
    persona = make_persona()
    save_persona(persona, tmp_path)

    expected_path = tmp_path / "woodworker.json"
    assert expected_path.exists(), "save_persona must write <name>.json into persona_dir"

    loaded = load_persona(expected_path)

    # Top-level fields
    assert loaded.name == persona.name
    assert loaded.version == persona.version
    assert loaded.seeds == persona.seeds
    assert loaded.created_at == persona.created_at
    assert loaded.total_sessions == persona.total_sessions
    assert loaded.expertise_level == persona.expertise_level

    # Fingerprint round-trip
    assert loaded.fingerprint.platform == persona.fingerprint.platform
    assert loaded.fingerprint.user_agent == persona.fingerprint.user_agent
    assert loaded.fingerprint.fonts == persona.fingerprint.fonts
    assert loaded.fingerprint.canvas_noise_seed == persona.fingerprint.canvas_noise_seed
    assert loaded.fingerprint.last_rotated is None

    # Topic tree round-trip
    assert len(loaded.topic_tree) == 1
    root = loaded.topic_tree[0]
    assert root.topic == "woodworking"
    assert root.depth == 0
    assert root.query_count == 12
    assert root.last_used == "2026-03-12T14:30:00Z"
    assert len(root.children) == 1

    child = root.children[0]
    assert child.topic == "hand tools"
    assert child.depth == 1
    assert child.query_count == 5
    assert child.children == []


def test_load_all_personas(tmp_path: Path) -> None:
    """load_all_personas returns all valid personas from a directory."""
    personas = [make_persona("woodworker"), make_persona("gardener")]
    for p in personas:
        save_persona(p, tmp_path)

    loaded = load_all_personas(tmp_path)

    assert len(loaded) == 2
    names = {p.name for p in loaded}
    assert names == {"woodworker", "gardener"}


def test_corrupted_persona_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A corrupted JSON file is skipped with a warning; valid files still load."""
    # Write a valid persona
    save_persona(make_persona("valid_one"), tmp_path)

    # Write an invalid JSON file alongside it
    bad_file = tmp_path / "corrupt.json"
    bad_file.write_text("{ this is not valid json }", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        loaded = load_all_personas(tmp_path)

    # Only the valid persona came through
    assert len(loaded) == 1
    assert loaded[0].name == "valid_one"

    # A warning was emitted mentioning the bad file
    assert any("corrupt.json" in record.message for record in caplog.records), (
        "Expected a warning log message containing the corrupted file's name"
    )


def test_nested_topic_tree_round_trips(tmp_path: Path) -> None:
    """Deep nesting (3+ levels) is preserved exactly through a save/load cycle."""
    # Build a 4-level-deep chain: root → l1 → l2 → l3
    l3 = TopicNode(topic="mortise and tenon", depth=3, query_count=2, last_used=None)
    l2 = TopicNode(topic="joinery", depth=2, query_count=4, last_used=None, children=[l3])
    l1 = TopicNode(topic="hand tools", depth=1, query_count=6, last_used=None, children=[l2])
    root = TopicNode(topic="woodworking", depth=0, query_count=10, last_used=None, children=[l1])

    persona = PersonaState(
        name="deep_thinker",
        version=2,
        seeds=["woodworking"],
        topic_tree=[root],
        fingerprint=make_fingerprint(),
        created_at="2026-03-12T10:00:00Z",
        total_sessions=0,
    )

    save_persona(persona, tmp_path)
    loaded = load_persona(tmp_path / "deep_thinker.json")

    # Walk the tree to verify all four levels survived
    n0 = loaded.topic_tree[0]
    assert n0.topic == "woodworking" and n0.depth == 0
    n1 = n0.children[0]
    assert n1.topic == "hand tools" and n1.depth == 1
    n2 = n1.children[0]
    assert n2.topic == "joinery" and n2.depth == 2
    n3 = n2.children[0]
    assert n3.topic == "mortise and tenon" and n3.depth == 3
    assert n3.children == []
    assert n3.last_used is None


def test_json_file_format_matches_spec(tmp_path: Path) -> None:
    """
    The raw on-disk JSON has the keys mandated by the spec.

    This guards against the implementation silently using different key names
    or nesting structures that would break external tooling or future migrations.
    """
    persona = make_persona()
    save_persona(persona, tmp_path)

    raw = json.loads((tmp_path / "woodworker.json").read_text(encoding="utf-8"))

    # Top-level keys required by spec
    for key in ("name", "version", "seeds", "created_at", "total_sessions", "fingerprint", "topic_tree"):
        assert key in raw, f"Missing required top-level key: {key!r}"

    # Topic tree node keys
    node = raw["topic_tree"][0]
    for key in ("topic", "depth", "query_count", "last_used", "children"):
        assert key in node, f"Missing required topic node key: {key!r}"
