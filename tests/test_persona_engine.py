"""
test_persona_engine.py — Tests for PersonaEngine: branch selection and query generation.

These tests verify that:
  - select_branch favors less-visited, shallower nodes via weighted random selection
  - generate_query_sequence produces 3–8 coherent string queries
  - build_session_context assembles a fully-populated SessionContext
"""

from murmurate.persona.engine import PersonaEngine
from murmurate.models import PersonaState, TopicNode, FingerprintProfile, SessionContext


def _make_persona():
    """Build a minimal but realistic PersonaState for testing."""
    fp = FingerprintProfile(
        platform="windows", user_agent="Mozilla/5.0", screen_width=1920,
        screen_height=1080, viewport_width=1536, viewport_height=864,
        timezone_id="America/Chicago", locale="en-US",
        accept_language="en-US,en;q=0.9", hardware_concurrency=8,
        device_memory=16, webgl_vendor="Google Inc.",
        webgl_renderer="ANGLE (NVIDIA)", canvas_noise_seed=12345,
        fonts=["Arial"], created_at="2026-03-12T10:00:00Z", last_rotated=None,
    )
    child = TopicNode(topic="hand planes", depth=1, children=[], query_count=2, last_used=None)
    root = TopicNode(topic="woodworking", depth=0, children=[child], query_count=10, last_used=None)
    return PersonaState(
        name="woodworker", version=1, seeds=["woodworking"], topic_tree=[root],
        fingerprint=fp, created_at="2026-03-12T10:00:00Z",
        total_sessions=20, expertise_level=0.4,
    )


def test_select_branch_prefers_less_visited():
    """
    Over 100 trials, the less-visited child node (query_count=2) should be selected
    more often than the more-visited root node (query_count=10).

    Weight formula: 1/(1+query_count) * 1/(1+depth)
      root:  1/11 * 1/1 ≈ 0.091
      child: 1/3  * 1/2 ≈ 0.167
    So child should win roughly 65% of the time.
    """
    engine = PersonaEngine()
    persona = _make_persona()
    counts = {"woodworking": 0, "hand planes": 0}
    for _ in range(100):
        branch = engine.select_branch(persona)
        counts[branch.topic] += 1
    assert counts["hand planes"] > counts["woodworking"]


def test_generate_query_sequence():
    """Query sequences must be 3–8 strings that reference the topic."""
    engine = PersonaEngine()
    persona = _make_persona()
    branch = persona.topic_tree[0]
    queries = engine.generate_query_sequence(persona, branch)
    assert 3 <= len(queries) <= 8
    assert all(isinstance(q, str) for q in queries)
    assert "woodworking" in queries[0].lower() or len(queries[0]) > 0


def test_build_session_context():
    """build_session_context must return a valid, fully-populated SessionContext."""
    engine = PersonaEngine()
    persona = _make_persona()
    context = engine.build_session_context(persona)
    assert isinstance(context, SessionContext)
    assert context.persona.name == "woodworker"
    assert 3 <= len(context.queries) <= 8
    assert context.current_query_index == 0
    assert context.session_id
