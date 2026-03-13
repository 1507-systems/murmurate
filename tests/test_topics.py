"""Tests for built-in topic pools (src/murmurate/persona/topics.py)."""

import pytest

from murmurate.persona.topics import get_random_seeds, load_topic_pools

EXPECTED_POOLS = {"hobbies", "academic", "shopping", "travel", "professional"}


def test_load_topic_pools():
    """All 5 expected pools are loaded, each with more than 10 entries."""
    pools = load_topic_pools()

    assert set(pools.keys()) == EXPECTED_POOLS, (
        f"Expected pools {EXPECTED_POOLS}, got {set(pools.keys())}"
    )

    for name, topics in pools.items():
        assert len(topics) > 10, (
            f"Pool '{name}' has only {len(topics)} entries; expected > 10"
        )
        # Sanity-check: every entry must be a non-empty string
        for topic in topics:
            assert isinstance(topic, str) and topic, (
                f"Pool '{name}' contains a non-string or empty entry: {topic!r}"
            )


def test_get_random_seeds():
    """Returns the requested count and every seed is a string."""
    seeds = get_random_seeds(10)

    assert len(seeds) == 10, f"Expected 10 seeds, got {len(seeds)}"
    for seed in seeds:
        assert isinstance(seed, str) and seed, (
            f"Seed is not a non-empty string: {seed!r}"
        )


def test_get_random_seeds_no_duplicates():
    """10 seeds drawn without replacement — all must be unique."""
    seeds = get_random_seeds(10)

    assert len(seeds) == len(set(seeds)), (
        f"Duplicate seeds found: {seeds}"
    )


def test_get_random_seeds_count_zero():
    """Requesting 0 seeds returns an empty list without error."""
    seeds = get_random_seeds(0)
    assert seeds == []


def test_get_random_seeds_exceeds_available():
    """Requesting more seeds than available topics raises ValueError."""
    pools = load_topic_pools()
    total = sum(len(v) for v in pools.values())

    with pytest.raises(ValueError, match="only"):
        get_random_seeds(total + 1)


def test_get_random_seeds_full_pool():
    """Can request exactly as many seeds as there are topics without error."""
    pools = load_topic_pools()
    total = sum(len(v) for v in pools.values())

    seeds = get_random_seeds(total)
    assert len(seeds) == total
    assert len(set(seeds)) == total
