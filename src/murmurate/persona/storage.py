"""
storage.py — JSON serialization/deserialization for PersonaState.

Each persona is stored as a single JSON file named `<persona.name>.json` inside
a configured directory. The on-disk format mirrors the field names used by the
dataclasses so there is no translation layer — this keeps migrations easy.

Key design decisions:
- `dataclasses.asdict()` handles the flat/nested dict conversion for writing,
  which recursively converts nested dataclasses (FingerprintProfile, TopicNode)
  automatically. We only need custom logic for *reading* back.
- TopicNode trees are recursive; deserialization uses a dedicated helper that
  walks the children list bottom-up.
- Corrupted files are skipped with a WARNING log rather than raising, so a single
  bad file never blocks the rest of the persona library from loading.
"""

import json
import logging
from dataclasses import asdict
from pathlib import Path

from murmurate.models import FingerprintProfile, PersonaState, TopicNode

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _node_from_dict(d: dict) -> TopicNode:
    """
    Recursively reconstruct a TopicNode (and all its descendants) from a dict.

    `dataclasses.asdict()` serializes children as a list of plain dicts, so we
    need this explicit reconstruction rather than a simple `TopicNode(**d)`.
    """
    return TopicNode(
        topic=d["topic"],
        depth=d["depth"],
        query_count=d.get("query_count", 0),
        last_used=d.get("last_used"),
        # Recurse: each child is itself a dict that must be reconstructed
        children=[_node_from_dict(c) for c in d.get("children", [])],
    )


def _persona_from_dict(d: dict) -> PersonaState:
    """
    Reconstruct a PersonaState from a parsed JSON dict.

    FingerprintProfile and TopicNode are nested dataclasses that `json.load`
    leaves as plain dicts; we rebuild them explicitly here.
    """
    fp_dict = d["fingerprint"]
    fingerprint = FingerprintProfile(
        platform=fp_dict["platform"],
        user_agent=fp_dict["user_agent"],
        screen_width=fp_dict["screen_width"],
        screen_height=fp_dict["screen_height"],
        viewport_width=fp_dict["viewport_width"],
        viewport_height=fp_dict["viewport_height"],
        timezone_id=fp_dict["timezone_id"],
        locale=fp_dict["locale"],
        accept_language=fp_dict["accept_language"],
        hardware_concurrency=fp_dict["hardware_concurrency"],
        device_memory=fp_dict["device_memory"],
        webgl_vendor=fp_dict["webgl_vendor"],
        webgl_renderer=fp_dict["webgl_renderer"],
        canvas_noise_seed=fp_dict["canvas_noise_seed"],
        fonts=fp_dict["fonts"],
        created_at=fp_dict["created_at"],
        last_rotated=fp_dict.get("last_rotated"),
    )

    topic_tree = [_node_from_dict(n) for n in d.get("topic_tree", [])]

    return PersonaState(
        name=d["name"],
        version=d["version"],
        seeds=d["seeds"],
        topic_tree=topic_tree,
        fingerprint=fingerprint,
        created_at=d["created_at"],
        total_sessions=d.get("total_sessions", 0),
        expertise_level=d.get("expertise_level", 0.0),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_persona(persona: PersonaState, persona_dir: Path) -> None:
    """
    Serialize *persona* to `{persona_dir}/{persona.name}.json`.

    Uses `dataclasses.asdict()` which recursively converts all nested
    dataclasses to plain dicts, giving us a clean JSON-serializable structure
    with no extra mapping code.

    The directory must already exist; this function does not create it to avoid
    silently writing personas to unexpected locations.
    """
    path = persona_dir / f"{persona.name}.json"
    data = asdict(persona)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_persona(path: Path) -> PersonaState:
    """
    Deserialize a PersonaState from a JSON file at *path*.

    Raises `json.JSONDecodeError` or `KeyError` if the file is missing required
    fields. Callers that want fault-tolerant loading should use `load_all_personas`
    instead, which skips bad files with a warning.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _persona_from_dict(raw)


def load_all_personas(persona_dir: Path) -> list[PersonaState]:
    """
    Load every `*.json` file in *persona_dir* as a PersonaState.

    Files that cannot be parsed (invalid JSON, missing required fields) are
    skipped and a WARNING is logged naming the problematic file. This lets the
    application start even if a single persona file is accidentally corrupted.

    Returns an empty list if *persona_dir* contains no `.json` files.
    """
    personas: list[PersonaState] = []

    for json_file in sorted(persona_dir.glob("*.json")):
        try:
            personas.append(load_persona(json_file))
        except Exception as exc:
            # Log the filename prominently so operators can locate and repair it
            log.warning(
                "Skipping corrupted persona file %s: %s",
                json_file.name,
                exc,
            )

    return personas
