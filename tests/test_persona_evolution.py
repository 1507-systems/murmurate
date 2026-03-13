"""
tests/test_persona_evolution.py — Tests for TF-IDF topic evolution.

Follows TDD: tests are written before the implementation exists.
"""

from murmurate.persona.evolution import extract_subtopics, evolve_topic_tree
from murmurate.models import TopicNode


def test_extract_subtopics_from_content():
    content_snippets = [
        "Best hand planes for beginners — Stanley No. 4 vs No. 5",
        "How to restore a vintage hand plane — japanning and blade sharpening",
        "Hand plane buying guide: block planes, jack planes, smoothing planes",
    ]
    subtopics = extract_subtopics(
        parent_topic="hand planes",
        content_snippets=content_snippets,
        max_topics=5,
        drift_rate=0.1,
    )
    assert len(subtopics) > 0
    assert len(subtopics) <= 5
    assert all(isinstance(t, str) for t in subtopics)


def test_extract_subtopics_filters_parent():
    content_snippets = ["hand planes are great tools for woodworking"]
    subtopics = extract_subtopics(
        parent_topic="hand planes",
        content_snippets=content_snippets,
        max_topics=5,
        drift_rate=0.0,
    )
    assert "hand planes" not in [s.lower() for s in subtopics]


def test_evolve_topic_tree_adds_children():
    root = TopicNode(topic="woodworking", depth=0, children=[], query_count=1, last_used=None)
    new_subtopics = ["hand planes", "wood turning", "joinery"]
    evolve_topic_tree(root, new_subtopics, max_depth=5)
    assert len(root.children) == 3
    assert root.children[0].topic == "hand planes"
    assert root.children[0].depth == 1


def test_evolve_topic_tree_respects_depth_limit():
    node = TopicNode(topic="root", depth=0, children=[], query_count=0, last_used=None)
    current = node
    for i in range(4):
        child = TopicNode(topic=f"level-{i+1}", depth=i+1, children=[], query_count=0, last_used=None)
        current.children.append(child)
        current = child
    evolve_topic_tree(current, ["too-deep"], max_depth=5)
    assert len(current.children) == 0


def test_evolve_topic_tree_no_duplicates():
    root = TopicNode(topic="cooking", depth=0, children=[
        TopicNode(topic="pasta", depth=1, children=[], query_count=0, last_used=None),
    ], query_count=1, last_used=None)
    evolve_topic_tree(root, ["pasta", "grilling"], max_depth=5)
    topics = [c.topic for c in root.children]
    assert topics.count("pasta") == 1
    assert "grilling" in topics
