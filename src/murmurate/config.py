"""
config.py — Configuration loading for Murmurate.

The config system follows a simple priority chain for locating the config
directory:
  1. CLI --config-dir flag (explicit, highest priority)
  2. MURMURATE_CONFIG environment variable
  3. ~/.config/murmurate/ (default fallback)

The config file itself is config.toml inside that directory. If the file is
absent, all defaults are used — this makes Murmurate work out-of-the-box with
zero configuration.

TOML schema notes:
  - sessions_per_hour may be written as an inline table:
        sessions_per_hour = { min = 3, max = 8 }
    which flattens to sessions_per_hour_min / sessions_per_hour_max.
  - Unknown keys at any level are silently ignored so newer config files
    remain backward-compatible with older Murmurate builds.
  - config_version > 1 raises ValueError; it's reserved for future
    breaking-change migrations.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Sub-config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SchedulerConfig:
    """Controls when and how often browsing sessions are scheduled.

    sessions_per_hour_min / _max define a random range sampled each hour.
    peak_hours contains HH:MM strings; sessions near those times get a small
    frequency boost.  quiet_hours_start / _end define a window where the
    scheduler stops entirely.
    """
    sessions_per_hour_min: int = 3
    sessions_per_hour_max: int = 8
    active_hours_start: str = "07:00"
    active_hours_end: str = "23:00"
    active_hours_timezone: str = "America/New_York"
    peak_hours: list[str] = field(default_factory=lambda: ["10:00", "20:00"])
    quiet_hours_start: str = "23:30"
    quiet_hours_end: str = "06:30"
    # Probability [0,1] of firing an extra "burst" session in any given slot
    burst_probability: float = 0.15


@dataclass
class RateLimitConfig:
    """Network-level rate limiting to avoid triggering anti-bot defenses.

    global_bandwidth_mbps caps total outbound throughput across all sessions.
    default_per_domain_rpm is the default requests-per-minute ceiling applied
    to each domain unless a plugin overrides it.
    """
    global_bandwidth_mbps: int = 5
    default_per_domain_rpm: int = 10


@dataclass
class TransportConfig:
    """Controls the mix of HTTP vs browser transports and browser behavior.

    browser_ratio is the fraction [0,1] of sessions that use Playwright.
    The remainder use lightweight aiohttp HTTP transport.
    """
    browser_ratio: float = 0.3
    browser_pool_size: int = 2
    headless: bool = True
    typing_wpm_min: int = 40
    typing_wpm_max: int = 80
    # When True, adds small random offsets to simulated mouse movements
    mouse_jitter: bool = True


@dataclass
class PersonaConfig:
    """Governs automatic persona creation and how personas evolve over time.

    auto_generate_count: how many personas to create on first run if none exist.
    drift_rate: how quickly a persona's expertise_level drifts toward a topic.
    max_tree_depth: maximum depth of the topic tree before pruning kicks in.
    """
    auto_generate_count: int = 3
    drift_rate: float = 0.1
    max_tree_depth: int = 5


@dataclass
class PluginConfig:
    """Which plugins are active.

    enabled: plugins that will be used by the scheduler.
    disabled: explicit opt-out list (useful for overriding defaults).
    If a plugin name appears in both lists, disabled wins.
    """
    enabled: list[str] = field(default_factory=lambda: [
        "google", "duckduckgo", "youtube", "amazon", "reddit", "wikipedia"
    ])
    disabled: list[str] = field(default_factory=lambda: ["bing"])


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------

@dataclass
class MurmurateConfig:
    """Root configuration object for Murmurate.

    Holds nested sub-configs for each subsystem plus a small set of top-level
    options.  Constructed by load_config(); callers should never build this
    directly (though it's fine for tests that just want defaults).
    """
    config_version: int = 1
    respect_robots_txt: bool = False
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    plugin: PluginConfig = field(default_factory=PluginConfig)


# ---------------------------------------------------------------------------
# Directory resolution
# ---------------------------------------------------------------------------

def resolve_config_dir(cli_flag: Path | None) -> Path:
    """Return the config directory, respecting the three-tier priority chain.

    Priority:
      1. cli_flag — if the caller passes a Path, use it as-is.
      2. MURMURATE_CONFIG env var — parsed as a Path.
      3. ~/.config/murmurate/ — the XDG-ish default.

    The returned path is not required to exist; callers should handle a
    missing directory gracefully (load_config does this already).
    """
    if cli_flag is not None:
        return cli_flag

    env_val = os.environ.get("MURMURATE_CONFIG")
    if env_val:
        return Path(env_val)

    return Path.home() / ".config" / "murmurate"


# ---------------------------------------------------------------------------
# TOML parsing helpers
# ---------------------------------------------------------------------------

def _build_scheduler(raw: dict) -> SchedulerConfig:
    """Parse a [scheduler] TOML table into a SchedulerConfig.

    The sessions_per_hour key may be either:
      - An inline table: sessions_per_hour = { min = 3, max = 8 }
      - Flat keys:       sessions_per_hour_min = 3 / sessions_per_hour_max = 8

    Both forms are accepted; the inline table form takes precedence if present.
    Unknown keys are silently ignored.
    """
    defaults = SchedulerConfig()

    # Flatten the inline-table form if present
    sph = raw.get("sessions_per_hour")
    if isinstance(sph, dict):
        sph_min = sph.get("min", defaults.sessions_per_hour_min)
        sph_max = sph.get("max", defaults.sessions_per_hour_max)
    else:
        sph_min = raw.get("sessions_per_hour_min", defaults.sessions_per_hour_min)
        sph_max = raw.get("sessions_per_hour_max", defaults.sessions_per_hour_max)

    return SchedulerConfig(
        sessions_per_hour_min=sph_min,
        sessions_per_hour_max=sph_max,
        active_hours_start=raw.get("active_hours_start", defaults.active_hours_start),
        active_hours_end=raw.get("active_hours_end", defaults.active_hours_end),
        active_hours_timezone=raw.get("active_hours_timezone", defaults.active_hours_timezone),
        peak_hours=raw.get("peak_hours", defaults.peak_hours),
        quiet_hours_start=raw.get("quiet_hours_start", defaults.quiet_hours_start),
        quiet_hours_end=raw.get("quiet_hours_end", defaults.quiet_hours_end),
        burst_probability=raw.get("burst_probability", defaults.burst_probability),
    )


def _build_rate_limit(raw: dict) -> RateLimitConfig:
    """Parse a [rate_limit] TOML table, ignoring unknown keys."""
    defaults = RateLimitConfig()
    return RateLimitConfig(
        global_bandwidth_mbps=raw.get("global_bandwidth_mbps", defaults.global_bandwidth_mbps),
        default_per_domain_rpm=raw.get("default_per_domain_rpm", defaults.default_per_domain_rpm),
    )


def _build_transport(raw: dict) -> TransportConfig:
    """Parse a [transport] TOML table, ignoring unknown keys."""
    defaults = TransportConfig()
    return TransportConfig(
        browser_ratio=raw.get("browser_ratio", defaults.browser_ratio),
        browser_pool_size=raw.get("browser_pool_size", defaults.browser_pool_size),
        headless=raw.get("headless", defaults.headless),
        typing_wpm_min=raw.get("typing_wpm_min", defaults.typing_wpm_min),
        typing_wpm_max=raw.get("typing_wpm_max", defaults.typing_wpm_max),
        mouse_jitter=raw.get("mouse_jitter", defaults.mouse_jitter),
    )


def _build_persona(raw: dict) -> PersonaConfig:
    """Parse a [persona] TOML table, ignoring unknown keys."""
    defaults = PersonaConfig()
    return PersonaConfig(
        auto_generate_count=raw.get("auto_generate_count", defaults.auto_generate_count),
        drift_rate=raw.get("drift_rate", defaults.drift_rate),
        max_tree_depth=raw.get("max_tree_depth", defaults.max_tree_depth),
    )


def _build_plugin(raw: dict) -> PluginConfig:
    """Parse a [plugin] TOML table, ignoring unknown keys."""
    defaults = PluginConfig()
    return PluginConfig(
        enabled=raw.get("enabled", defaults.enabled),
        disabled=raw.get("disabled", defaults.disabled),
    )


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_config(config_dir: Path) -> MurmurateConfig:
    """Load MurmurateConfig from config_dir/config.toml.

    Behaviour:
      - If config.toml does not exist, returns a fully-defaulted MurmurateConfig.
      - Sections and keys present in the file override their defaults; everything
        else stays at its default value.
      - Unknown sections and keys are silently ignored (forward-compatibility).
      - If config_version in the file is greater than 1, raises ValueError because
        that signals a schema version this build cannot handle.

    Raises:
        ValueError: if config_version > 1.
        tomllib.TOMLDecodeError: if the TOML is syntactically invalid.
    """
    config_file = config_dir / "config.toml"

    # Missing file → pure defaults, no error
    if not config_file.exists():
        return MurmurateConfig()

    with config_file.open("rb") as fh:
        raw = tomllib.load(fh)

    # Version guard — must check before building anything else so we surface
    # the error clearly rather than silently misinterpreting future schema keys.
    config_version = raw.get("config_version", 1)
    if config_version > 1:
        raise ValueError(
            f"Unsupported config_version {config_version!r}. "
            "This version of Murmurate only supports config_version = 1. "
            "Please upgrade Murmurate or downgrade your config file."
        )

    return MurmurateConfig(
        config_version=config_version,
        respect_robots_txt=raw.get("respect_robots_txt", False),
        scheduler=_build_scheduler(raw.get("scheduler", {})),
        rate_limit=_build_rate_limit(raw.get("rate_limit", {})),
        transport=_build_transport(raw.get("transport", {})),
        persona=_build_persona(raw.get("persona", {})),
        plugin=_build_plugin(raw.get("plugin", {})),
    )
