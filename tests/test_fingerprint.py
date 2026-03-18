"""
test_fingerprint.py — Tests for persona fingerprint profile generation.

Covers type correctness, internal consistency, and statistical properties.
"""

import json
from pathlib import Path


from murmurate.models import FingerprintProfile
from murmurate.persona.fingerprint import (
    _build_accept_language,
    _weighted_choice,
    _weighted_choice_dict,
    generate_fingerprint,
)

# Known platform keys so we can assert membership without coupling to the data file
_VALID_PLATFORMS = {"windows", "macos", "linux", "android", "ios"}

# User-agent substrings that distinguish each platform's UA pool
_PLATFORM_UA_MARKERS = {
    "windows": "Windows",
    "macos": "Macintosh",
    "linux": "Linux",
    "android": "Android",
    "ios": "iPhone",
}

# Load the canonical font pools from the data files so the test verifies that
# the fingerprint's font list is a strict subset of the correct platform pool —
# rather than checking for a specific font that may be absent in a small sample.
_DATA_DIR = Path(__file__).parent.parent / "data"
_PLATFORM_FONT_POOLS: dict[str, set[str]] = {
    platform: set(fonts)
    for platform, fonts in json.loads((_DATA_DIR / "fingerprints" / "fonts.json").read_text()).items()
}


# ---------------------------------------------------------------------------
# Basic type and validity checks
# ---------------------------------------------------------------------------


def test_generate_fingerprint_returns_profile():
    """generate_fingerprint() must return a FingerprintProfile with correct types."""
    fp = generate_fingerprint()

    assert isinstance(fp, FingerprintProfile), "Return type must be FingerprintProfile"
    assert isinstance(fp.platform, str) and fp.platform, "platform must be a non-empty string"
    assert fp.platform in _VALID_PLATFORMS, f"platform {fp.platform!r} is not a known value"
    assert isinstance(fp.user_agent, str) and fp.user_agent
    assert isinstance(fp.screen_width, int) and fp.screen_width > 0
    assert isinstance(fp.screen_height, int) and fp.screen_height > 0
    assert isinstance(fp.viewport_width, int) and fp.viewport_width > 0
    assert isinstance(fp.viewport_height, int) and fp.viewport_height > 0
    assert isinstance(fp.timezone_id, str) and fp.timezone_id
    assert isinstance(fp.locale, str) and fp.locale
    assert isinstance(fp.accept_language, str) and fp.accept_language
    assert isinstance(fp.hardware_concurrency, int) and fp.hardware_concurrency > 0
    assert isinstance(fp.device_memory, int) and fp.device_memory > 0
    assert isinstance(fp.webgl_vendor, str) and fp.webgl_vendor
    assert isinstance(fp.webgl_renderer, str) and fp.webgl_renderer
    assert isinstance(fp.canvas_noise_seed, int)
    assert isinstance(fp.fonts, list) and len(fp.fonts) > 0
    assert isinstance(fp.created_at, str) and fp.created_at
    assert fp.last_rotated is None, "last_rotated should be None on initial creation"


def test_fingerprint_screen_dimensions_positive():
    """Screen and viewport dimensions must all be positive integers."""
    for _ in range(10):
        fp = generate_fingerprint()
        assert fp.screen_width > 0
        assert fp.screen_height > 0
        assert fp.viewport_width > 0
        assert fp.viewport_height > 0
        # Viewport should not exceed screen (common sense check)
        assert fp.viewport_width <= fp.screen_width
        assert fp.viewport_height <= fp.screen_height


# ---------------------------------------------------------------------------
# Internal consistency: platform-conditional fields must match their platform
# ---------------------------------------------------------------------------


def test_fingerprint_internal_consistency():
    """
    UA string and font list must come from the same platform that was selected.

    For each generated fingerprint we assert:
    1. The UA contains the expected OS-identifying substring for that platform.
    2. Every font in the fingerprint's list is drawn from the correct platform
       pool — none should come from a different platform's pool.

    100 samples gives ~99.99 % coverage of all five platforms at their natural
    weights; any cross-platform contamination would fail quickly.
    """
    for _ in range(100):
        fp = generate_fingerprint()
        platform = fp.platform

        # 1. UA marker check
        if platform in _PLATFORM_UA_MARKERS:
            marker = _PLATFORM_UA_MARKERS[platform]
            assert marker in fp.user_agent, (
                f"Platform {platform!r}: UA {fp.user_agent!r} missing expected marker {marker!r}"
            )

        # 2. Font pool membership check — all fonts must come from the platform's pool
        if platform in _PLATFORM_FONT_POOLS:
            allowed = _PLATFORM_FONT_POOLS[platform]
            for font in fp.fonts:
                assert font in allowed, (
                    f"Platform {platform!r}: font {font!r} is not in the platform's font pool. "
                    f"Font list: {fp.fonts}"
                )


def test_windows_ua_and_fonts():
    """Smoke test: a Windows fingerprint has Windows UA and all fonts from Windows pool."""
    # Keep regenerating until we get a Windows one (probability 0.72 so fast)
    fp = None
    for _ in range(50):
        candidate = generate_fingerprint()
        if candidate.platform == "windows":
            fp = candidate
            break

    assert fp is not None, "Failed to get a Windows fingerprint in 50 tries"
    assert "Windows" in fp.user_agent
    # All fonts must come from the Windows pool (pool membership, not a single font)
    windows_pool = _PLATFORM_FONT_POOLS["windows"]
    for font in fp.fonts:
        assert font in windows_pool, f"Windows fingerprint has non-Windows font: {font!r}"


def test_macos_ua_and_fonts():
    """Smoke test: a macOS fingerprint has Macintosh UA and all fonts from macOS pool."""
    fp = None
    for _ in range(100):
        candidate = generate_fingerprint()
        if candidate.platform == "macos":
            fp = candidate
            break

    assert fp is not None, "Failed to get a macOS fingerprint in 100 tries"
    assert "Macintosh" in fp.user_agent
    # All fonts must come from the macOS pool — do not assert a specific font
    # because the sampled subset of 8-12 may not include any given font
    macos_pool = _PLATFORM_FONT_POOLS["macos"]
    for font in fp.fonts:
        assert font in macos_pool, f"macOS fingerprint has non-macOS font: {font!r}"


# ---------------------------------------------------------------------------
# Timezone / locale consistency
# ---------------------------------------------------------------------------


def test_fingerprint_timezone_locale_consistency():
    """
    The accept_language header's primary language tag must match the locale.

    For example, locale "en-US" must produce accept_language starting with "en-US".
    The locale itself must be one of the five supported values.
    """
    valid_locales = {"en-US", "en-GB", "de-DE", "fr-FR", "ja-JP"}

    for _ in range(50):
        fp = generate_fingerprint()

        assert fp.locale in valid_locales, f"Unexpected locale: {fp.locale!r}"

        # accept_language must begin with the locale tag
        assert fp.accept_language.startswith(fp.locale), (
            f"accept_language {fp.accept_language!r} does not start with locale {fp.locale!r}"
        )

        # The language portion of accept_language must match locale's language prefix
        lang = fp.locale.split("-")[0]
        assert lang in fp.accept_language, (
            f"Language code {lang!r} not found in accept_language {fp.accept_language!r}"
        )


def test_fingerprint_timezone_belongs_to_locale():
    """
    Each timezone_id must be in the set of timezones defined for the fingerprint's locale.
    """
    locale_tz_map = {
        "en-US": {"America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"},
        "en-GB": {"Europe/London"},
        "de-DE": {"Europe/Berlin"},
        "fr-FR": {"Europe/Paris"},
        "ja-JP": {"Asia/Tokyo"},
    }

    for _ in range(50):
        fp = generate_fingerprint()
        allowed_timezones = locale_tz_map[fp.locale]
        assert fp.timezone_id in allowed_timezones, (
            f"timezone_id {fp.timezone_id!r} is not consistent with locale {fp.locale!r}"
        )


# ---------------------------------------------------------------------------
# Canvas noise seed
# ---------------------------------------------------------------------------


def test_fingerprint_deterministic_canvas_seed():
    """canvas_noise_seed must be an integer in [0, 2^32)."""
    for _ in range(20):
        fp = generate_fingerprint()
        assert isinstance(fp.canvas_noise_seed, int)
        assert 0 <= fp.canvas_noise_seed < 2**32, (
            f"canvas_noise_seed {fp.canvas_noise_seed} out of [0, 2^32) range"
        )


# ---------------------------------------------------------------------------
# Uniqueness / variability
# ---------------------------------------------------------------------------


def test_two_fingerprints_differ():
    """
    Any two independently generated fingerprints should differ in at least
    one field. (The probability that ALL fields match is astronomically small.)
    """
    fp1 = generate_fingerprint()
    fp2 = generate_fingerprint()

    differ = any([
        fp1.platform != fp2.platform,
        fp1.user_agent != fp2.user_agent,
        fp1.locale != fp2.locale,
        fp1.timezone_id != fp2.timezone_id,
        fp1.canvas_noise_seed != fp2.canvas_noise_seed,
        fp1.hardware_concurrency != fp2.hardware_concurrency,
        fp1.device_memory != fp2.device_memory,
        fp1.fonts != fp2.fonts,
    ])

    assert differ, "Two independently generated fingerprints were identical — suspicious"


# ---------------------------------------------------------------------------
# Font count
# ---------------------------------------------------------------------------


def test_fingerprint_font_count_in_range():
    """
    The fonts list must contain between min(8, pool_size) and min(12, pool_size) entries.

    Desktop platforms (windows, macos, linux) have 12+ fonts in their pool so
    the count is always in [8, 12]. Mobile platforms (android: 6, ios: 8) have
    smaller pools, so the implementation clamps both bounds to pool size.
    We verify that the count is always in [1, 12] and never exceeds pool size.
    """
    for _ in range(50):
        fp = generate_fingerprint()
        pool_size = len(_PLATFORM_FONT_POOLS[fp.platform])
        expected_lower = min(8, pool_size)
        expected_upper = min(12, pool_size)
        assert expected_lower <= len(fp.fonts) <= expected_upper, (
            f"Platform {fp.platform!r}: font count {len(fp.fonts)} outside "
            f"[{expected_lower}, {expected_upper}] (pool size: {pool_size})"
        )


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


def test_weighted_choice_respects_weights():
    """
    A heavily weighted item should win the majority of the time.
    We use a 2-item list with weights 0.99 / 0.01 and expect the first item
    to win at least 90 % of the time over 1000 draws.
    """
    items = [{"name": "heavy", "weight": 0.99}, {"name": "light", "weight": 0.01}]
    wins = sum(1 for _ in range(1000) if _weighted_choice(items)["name"] == "heavy")
    assert wins >= 900, f"heavy item won only {wins}/1000 times (expected ≥ 900)"


def test_weighted_choice_dict_returns_known_key():
    """_weighted_choice_dict must always return one of the input keys."""
    mapping = {"a": 0.5, "b": 0.3, "c": 0.2}
    for _ in range(100):
        result = _weighted_choice_dict(mapping)
        assert result in mapping


def test_build_accept_language():
    """_build_accept_language should produce correctly formatted header values."""
    assert _build_accept_language("en-US") == "en-US,en;q=0.9"
    assert _build_accept_language("de-DE") == "de-DE,de;q=0.9"
    assert _build_accept_language("ja-JP") == "ja-JP,ja;q=0.9"
