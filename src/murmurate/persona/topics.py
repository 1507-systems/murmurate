"""
Built-in topic pools for auto-persona seed generation.

Topic pools are stored as JSON arrays in data/topic_pools/ at the project root.
Each file represents a thematic category (hobbies, academic, shopping, etc.).
The pools are used to seed persona interest profiles with realistic, varied topics
without requiring the user to configure anything.
"""

import json
import random
from pathlib import Path


# Locate the data directory relative to this source file.
# File hierarchy: src/murmurate/persona/topics.py → 3 parents up → project root → data/
_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "topic_pools"


def load_topic_pools() -> dict[str, list[str]]:
    """Load all topic pool JSON files from the data directory.

    Each JSON file must be an array of strings. The pool name is derived from
    the filename without extension (e.g., hobbies.json → "hobbies").

    Returns:
        A dict mapping pool name → list of topic strings. Empty if no files found.

    Raises:
        ValueError: If a JSON file does not contain an array of strings.
    """
    pools: dict[str, list[str]] = {}

    if not _DATA_DIR.exists():
        return pools

    for json_file in sorted(_DATA_DIR.glob("*.json")):
        pool_name = json_file.stem
        with json_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
            raise ValueError(
                f"Topic pool file '{json_file.name}' must contain a JSON array of strings"
            )

        pools[pool_name] = data

    return pools


def get_random_seeds(count: int) -> list[str]:
    """Draw unique topic seeds from across all pools with uniform weighting.

    All topics from all pools are flattened into a single list and then sampled
    without replacement. This ensures no pool dominates — every topic has equal
    probability of selection regardless of its pool's size relative to others.

    Args:
        count: Number of unique topic seeds to return.

    Returns:
        A list of `count` unique topic strings chosen at random.

    Raises:
        ValueError: If `count` exceeds the total number of available topics.
    """
    pools = load_topic_pools()

    # Flatten all pools into a single deduplicated list to give uniform weighting
    # across all topics regardless of pool size differences.
    all_topics: list[str] = []
    for topics in pools.values():
        all_topics.extend(topics)

    if count > len(all_topics):
        raise ValueError(
            f"Requested {count} seeds but only {len(all_topics)} unique topics are available"
        )

    return random.sample(all_topics, count)
