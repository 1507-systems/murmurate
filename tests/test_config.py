"""
test_config.py — Tests for Murmurate config loading.

Tests are written first (TDD). They cover:
  - Default config when no file exists
  - Loading custom values from a TOML file
  - Missing config file falls back to defaults
  - config_version > 1 raises ValueError
  - resolve_config_dir picks up MURMURATE_CONFIG env var
  - CLI flag takes precedence over env var
  - Unknown TOML fields are silently ignored
"""

import os
import textwrap
from pathlib import Path

import pytest

from murmurate.config import (
    MurmurateConfig,
    SchedulerConfig,
    RateLimitConfig,
    TransportConfig,
    PersonaConfig,
    PluginConfig,
    load_config,
    resolve_config_dir,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_toml(tmp_path: Path, content: str) -> Path:
    """Write a config.toml to tmp_path and return the directory."""
    (tmp_path / "config.toml").write_text(textwrap.dedent(content))
    return tmp_path


# ---------------------------------------------------------------------------
# resolve_config_dir
# ---------------------------------------------------------------------------

class TestResolveConfigDir:
    def test_resolve_config_dir_from_env(self, tmp_path, monkeypatch):
        """MURMURATE_CONFIG env var is used when no CLI flag is given."""
        monkeypatch.setenv("MURMURATE_CONFIG", str(tmp_path))
        monkeypatch.delenv("MURMURATE_CONFIG", raising=False)  # clean slate
        monkeypatch.setenv("MURMURATE_CONFIG", str(tmp_path))
        result = resolve_config_dir(None)
        assert result == tmp_path

    def test_resolve_config_dir_cli_flag_takes_precedence(self, tmp_path, monkeypatch):
        """CLI flag beats MURMURATE_CONFIG env var."""
        other = tmp_path / "other"
        other.mkdir()
        monkeypatch.setenv("MURMURATE_CONFIG", str(tmp_path))
        result = resolve_config_dir(other)
        assert result == other

    def test_resolve_config_dir_default(self, monkeypatch):
        """Falls back to ~/.config/murmurate/ when nothing is set."""
        monkeypatch.delenv("MURMURATE_CONFIG", raising=False)
        result = resolve_config_dir(None)
        assert result == Path.home() / ".config" / "murmurate"


# ---------------------------------------------------------------------------
# load_config — defaults
# ---------------------------------------------------------------------------

class TestDefaultConfig:
    def test_default_config_loads(self, tmp_path):
        """load_config on an empty directory returns a fully populated MurmurateConfig."""
        cfg = load_config(tmp_path)
        assert isinstance(cfg, MurmurateConfig)
        assert isinstance(cfg.scheduler, SchedulerConfig)
        assert isinstance(cfg.rate_limit, RateLimitConfig)
        assert isinstance(cfg.transport, TransportConfig)
        assert isinstance(cfg.persona, PersonaConfig)
        assert isinstance(cfg.plugin, PluginConfig)

    def test_default_config_values(self, tmp_path):
        """Spot-check default values across each sub-config."""
        cfg = load_config(tmp_path)
        # Scheduler
        assert cfg.scheduler.sessions_per_hour_min == 3
        assert cfg.scheduler.sessions_per_hour_max == 8
        assert cfg.scheduler.active_hours_start == "07:00"
        assert cfg.scheduler.active_hours_end == "23:00"
        assert cfg.scheduler.active_hours_timezone == "America/New_York"
        assert cfg.scheduler.peak_hours == ["10:00", "20:00"]
        assert cfg.scheduler.quiet_hours_start == "23:30"
        assert cfg.scheduler.quiet_hours_end == "06:30"
        assert cfg.scheduler.burst_probability == pytest.approx(0.15)
        # Rate limit
        assert cfg.rate_limit.global_bandwidth_mbps == 5
        assert cfg.rate_limit.default_per_domain_rpm == 10
        # Transport
        assert cfg.transport.browser_ratio == pytest.approx(0.3)
        assert cfg.transport.browser_pool_size == 2
        assert cfg.transport.headless is True
        assert cfg.transport.typing_wpm_min == 40
        assert cfg.transport.typing_wpm_max == 80
        assert cfg.transport.mouse_jitter is True
        # Persona
        assert cfg.persona.auto_generate_count == 3
        assert cfg.persona.drift_rate == pytest.approx(0.1)
        assert cfg.persona.max_tree_depth == 5
        # Plugin
        assert "google" in cfg.plugin.enabled
        assert "bing" in cfg.plugin.disabled
        # Top-level
        assert cfg.config_version == 1
        assert cfg.respect_robots_txt is False

    def test_load_config_missing_file_uses_defaults(self, tmp_path):
        """Missing config.toml is not an error — returns defaults silently."""
        assert not (tmp_path / "config.toml").exists()
        cfg = load_config(tmp_path)
        assert cfg.scheduler.sessions_per_hour_min == 3


# ---------------------------------------------------------------------------
# load_config — custom TOML values
# ---------------------------------------------------------------------------

class TestLoadConfigFromToml:
    def test_load_config_from_toml(self, tmp_path):
        """Custom TOML values override defaults correctly."""
        write_toml(tmp_path, """
            config_version = 1
            respect_robots_txt = true

            [scheduler]
            sessions_per_hour = { min = 5, max = 12 }
            active_hours_start = "08:00"
            active_hours_end  = "22:00"
            active_hours_timezone = "America/Chicago"
            peak_hours = ["09:00", "18:00"]
            quiet_hours_start = "22:30"
            quiet_hours_end   = "07:00"
            burst_probability = 0.25

            [rate_limit]
            global_bandwidth_mbps = 10
            default_per_domain_rpm = 20

            [transport]
            browser_ratio = 0.5
            browser_pool_size = 4
            headless = false
            typing_wpm_min = 50
            typing_wpm_max = 100
            mouse_jitter = false

            [persona]
            auto_generate_count = 5
            drift_rate = 0.2
            max_tree_depth = 8

            [plugin]
            enabled  = ["google", "bing"]
            disabled = ["amazon"]
        """)
        cfg = load_config(tmp_path)

        assert cfg.respect_robots_txt is True
        assert cfg.scheduler.sessions_per_hour_min == 5
        assert cfg.scheduler.sessions_per_hour_max == 12
        assert cfg.scheduler.active_hours_start == "08:00"
        assert cfg.scheduler.active_hours_timezone == "America/Chicago"
        assert cfg.scheduler.peak_hours == ["09:00", "18:00"]
        assert cfg.scheduler.burst_probability == pytest.approx(0.25)
        assert cfg.rate_limit.global_bandwidth_mbps == 10
        assert cfg.rate_limit.default_per_domain_rpm == 20
        assert cfg.transport.browser_ratio == pytest.approx(0.5)
        assert cfg.transport.headless is False
        assert cfg.transport.mouse_jitter is False
        assert cfg.persona.auto_generate_count == 5
        assert cfg.persona.drift_rate == pytest.approx(0.2)
        assert cfg.persona.max_tree_depth == 8
        assert cfg.plugin.enabled == ["google", "bing"]
        assert cfg.plugin.disabled == ["amazon"]

    def test_partial_toml_merges_with_defaults(self, tmp_path):
        """A TOML that sets only some keys leaves the rest at defaults."""
        write_toml(tmp_path, """
            [scheduler]
            active_hours_start = "09:00"
        """)
        cfg = load_config(tmp_path)
        # Overridden value
        assert cfg.scheduler.active_hours_start == "09:00"
        # Untouched default
        assert cfg.scheduler.sessions_per_hour_min == 3
        assert cfg.transport.headless is True


# ---------------------------------------------------------------------------
# load_config — inline table flattening
# ---------------------------------------------------------------------------

class TestInlineTableFlattening:
    def test_sessions_per_hour_inline_table(self, tmp_path):
        """sessions_per_hour = { min = X, max = Y } flattens to _min/_max fields."""
        write_toml(tmp_path, """
            [scheduler]
            sessions_per_hour = { min = 6, max = 15 }
        """)
        cfg = load_config(tmp_path)
        assert cfg.scheduler.sessions_per_hour_min == 6
        assert cfg.scheduler.sessions_per_hour_max == 15


# ---------------------------------------------------------------------------
# load_config — version guard
# ---------------------------------------------------------------------------

class TestConfigVersionGuard:
    def test_config_version_too_high_raises(self, tmp_path):
        """config_version > 1 raises ValueError."""
        write_toml(tmp_path, "config_version = 2\n")
        with pytest.raises(ValueError, match="config_version"):
            load_config(tmp_path)

    def test_config_version_1_is_valid(self, tmp_path):
        """config_version = 1 is accepted without error."""
        write_toml(tmp_path, "config_version = 1\n")
        cfg = load_config(tmp_path)
        assert cfg.config_version == 1


# ---------------------------------------------------------------------------
# load_config — unknown field tolerance
# ---------------------------------------------------------------------------

class TestUnknownFields:
    def test_unknown_fields_ignored(self, tmp_path):
        """Unknown top-level and nested TOML keys are silently dropped."""
        write_toml(tmp_path, """
            config_version = 1
            totally_unknown_key = "surprise"

            [scheduler]
            sessions_per_hour = { min = 3, max = 8 }
            nonexistent_field = 99

            [unknown_section]
            foo = "bar"
        """)
        # Should not raise
        cfg = load_config(tmp_path)
        assert cfg.scheduler.sessions_per_hour_min == 3
