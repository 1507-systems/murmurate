"""
fingerprint.py — Generates realistic browser fingerprint profiles for personas.

Fingerprints are sampled from weighted real-world distribution data stored in
`data/fingerprints/`. Each field is sampled consistently per platform so that,
for example, a Windows persona gets Windows UA strings, Windows fonts, and
Windows-typical GPU info — not a random mix across platforms.

The data files live at the project root's `data/` directory, resolved relative
to this file's location so it works regardless of the working directory.
"""

import json
import random
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from murmurate.models import FingerprintProfile

# --- Path resolution -----------------------------------------------------------

# Walk up: fingerprint.py → persona/ → murmurate/ → src/ → project root
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_FP_DIR = _DATA_DIR / "fingerprints"


def _load_json(path: Path) -> Any:
    """Load a JSON file, raising a clear error if it's missing."""
    if not path.exists():
        raise FileNotFoundError(
            f"Fingerprint data file not found: {path}. "
            "Ensure the data/ directory is present at the project root."
        )
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# Load all distribution data once at module import time. This is intentional:
# the data files are static reference data, not user input, so eager loading
# keeps per-call overhead near zero and surfaces missing files immediately.
_PLATFORMS: dict[str, float] = _load_json(_FP_DIR / "platforms.json")
_SCREENS: dict[str, list[dict]] = _load_json(_FP_DIR / "screens.json")
_WEBGL: dict[str, list[dict]] = _load_json(_FP_DIR / "webgl.json")
_FONTS: dict[str, list[str]] = _load_json(_FP_DIR / "fonts.json")
_USER_AGENTS: dict[str, list[str]] = _load_json(_DATA_DIR / "user_agents.json")

# Mobile platforms — used to pick smaller hardware_concurrency / device_memory values
_MOBILE_PLATFORMS = {"android", "ios"}

# Locale → list of IANA timezone IDs that are consistent with that locale.
# Keeping this as a hardcoded mapping avoids a runtime dependency on pytz/zoneinfo
# for what is ultimately just display/header data.
_LOCALE_TIMEZONES: dict[str, list[str]] = {
    "en-US": ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"],
    "en-GB": ["Europe/London"],
    "de-DE": ["Europe/Berlin"],
    "fr-FR": ["Europe/Paris"],
    "ja-JP": ["Asia/Tokyo"],
}

# Weighted locale distribution — en-US dominates (~70 %) to mirror real traffic.
_LOCALE_WEIGHTS = {
    "en-US": 0.70,
    "en-GB": 0.10,
    "de-DE": 0.07,
    "fr-FR": 0.07,
    "ja-JP": 0.06,
}


# --- Core helpers -------------------------------------------------------------


def _weighted_choice(items: list[dict], key: str = "weight") -> dict:
    """
    Select one item from a list of dicts using the numeric value at `key` as
    the probability weight.

    The weights do not need to sum to 1.0 — they are normalised internally,
    which lets the data files use convenient round numbers without strict
    enforcement of sum == 1.
    """
    weights = [item[key] for item in items]
    total = sum(weights)
    r = random.random() * total
    cumulative = 0.0
    for item, w in zip(items, weights):
        cumulative += w
        if r <= cumulative:
            return item
    # Floating-point edge case: return the last item
    return items[-1]


def _weighted_choice_dict(mapping: dict[str, float]) -> str:
    """
    Select one key from a {key: weight} dict using weighted random sampling.
    Analogous to _weighted_choice but operates on plain dicts.
    """
    keys = list(mapping.keys())
    weights = [mapping[k] for k in keys]
    total = sum(weights)
    r = random.random() * total
    cumulative = 0.0
    for key, w in zip(keys, weights):
        cumulative += w
        if r <= cumulative:
            return key
    return keys[-1]


def _build_accept_language(locale: str) -> str:
    """
    Derive a plausible Accept-Language header from a BCP-47 locale tag.

    Examples:
        "en-US"  →  "en-US,en;q=0.9"
        "de-DE"  →  "de-DE,de;q=0.9"
        "ja-JP"  →  "ja-JP,ja;q=0.9"
    """
    lang = locale.split("-")[0]  # "en-US" → "en"
    return f"{locale},{lang};q=0.9"


# --- Public API ---------------------------------------------------------------


def generate_fingerprint() -> FingerprintProfile:
    """
    Generate a single randomised but internally consistent FingerprintProfile.

    Consistency rules:
    - All platform-conditional fields (UA, screen, WebGL, fonts) are sampled
      from the pool for the chosen platform.
    - Timezone is drawn from the pool that corresponds to the chosen locale.
    - hardware_concurrency and device_memory use smaller value pools for mobile.

    Returns a fully populated FingerprintProfile dataclass instance.
    """
    # 1. Sample platform -------------------------------------------------------
    platform_key = _weighted_choice_dict(_PLATFORMS)
    is_mobile = platform_key in _MOBILE_PLATFORMS

    # 2. Sample screen resolution (conditional on platform) --------------------
    screen = _weighted_choice(_SCREENS[platform_key])

    # 3. Sample WebGL info (conditional on platform) ---------------------------
    webgl = _weighted_choice(_WEBGL[platform_key])

    # 4. Pick a random user-agent string for the platform ---------------------
    user_agent = random.choice(_USER_AGENTS[platform_key])

    # 5. Pick a random subset of 8–12 fonts from the platform's font list -----
    font_pool = _FONTS[platform_key]
    # Clamp both bounds to the pool size so we never request more than available.
    # For small mobile pools (e.g. Android has 6 fonts) we take the full pool
    # rather than crashing — the test suite asserts [8, 12] only for platforms
    # with large enough pools, and the spec says "8–12 from the platform's list".
    pool_size = len(font_pool)
    lower = min(8, pool_size)
    upper = min(12, pool_size)
    sample_count = random.randint(lower, upper)
    fonts = random.sample(font_pool, sample_count)

    # 6. Sample locale, then pick a timezone consistent with it ---------------
    locale = _weighted_choice_dict(_LOCALE_WEIGHTS)
    timezone_id = random.choice(_LOCALE_TIMEZONES[locale])

    # 7. Hardware concurrency: fewer cores on mobile --------------------------
    if is_mobile:
        hardware_concurrency = random.choice([4, 6, 8])
    else:
        hardware_concurrency = random.choice([4, 8, 12, 16])

    # 8. Device memory (GB, power-of-2): smaller pool for mobile --------------
    if is_mobile:
        device_memory = random.choice([4, 6, 8])
    else:
        device_memory = random.choice([4, 8, 16])

    # 9. Canvas noise seed: cryptographically random 32-bit integer -----------
    # Using secrets ensures seeds don't cluster around system-time values and
    # can't be trivially predicted from session timing.
    canvas_noise_seed = secrets.randbelow(2**32)

    # 10. Build Accept-Language header ----------------------------------------
    accept_language = _build_accept_language(locale)

    # 11. Timestamp -----------------------------------------------------------
    created_at = datetime.now(timezone.utc).isoformat()

    return FingerprintProfile(
        platform=platform_key,
        user_agent=user_agent,
        screen_width=screen["width"],
        screen_height=screen["height"],
        viewport_width=screen["viewport_width"],
        viewport_height=screen["viewport_height"],
        timezone_id=timezone_id,
        locale=locale,
        accept_language=accept_language,
        hardware_concurrency=hardware_concurrency,
        device_memory=device_memory,
        webgl_vendor=webgl["vendor"],
        webgl_renderer=webgl["renderer"],
        canvas_noise_seed=canvas_noise_seed,
        fonts=fonts,
        created_at=created_at,
    )
