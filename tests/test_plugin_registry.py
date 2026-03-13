"""
tests/test_plugin_registry.py — Tests for PluginRegistry.

Tests cover registration, bundled/user plugin loading, enable/disable controls,
failure tracking with auto-disable, cooldown expiry, and plugin info output.
"""

import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from murmurate.models import BrowseAction, SearchResult, SessionContext, TransportType
from murmurate.plugins.base import SitePlugin
from murmurate.plugins.registry import PluginRegistry


# ---------------------------------------------------------------------------
# Minimal concrete SitePlugin for use in tests
# ---------------------------------------------------------------------------

class DummyPlugin(SitePlugin):
    """Minimal concrete plugin used as a test fixture."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def domains(self) -> list[str]:
        return ["dummy.example.com"]

    @property
    def preferred_transport(self) -> TransportType:
        return TransportType.HTTP

    @property
    def rate_limit_rpm(self) -> int:
        return 30

    async def execute_search(self, context, transport):
        return []

    async def browse_result(self, result, context, transport):
        raise NotImplementedError


class AnotherPlugin(SitePlugin):
    """Second concrete plugin for multi-plugin tests."""

    @property
    def name(self) -> str:
        return "another"

    @property
    def domains(self) -> list[str]:
        return ["another.example.com"]

    @property
    def preferred_transport(self) -> TransportType:
        return TransportType.BROWSER

    @property
    def rate_limit_rpm(self) -> int:
        return 10

    async def execute_search(self, context, transport):
        return []

    async def browse_result(self, result, context, transport):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry():
    return PluginRegistry()


@pytest.fixture
def registry_with_dummy():
    reg = PluginRegistry()
    reg.register(DummyPlugin())
    return reg


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_register_adds_plugin(registry):
    plugin = DummyPlugin()
    registry.register(plugin)
    assert registry.get_plugin("dummy") is plugin


def test_register_multiple_plugins(registry):
    registry.register(DummyPlugin())
    registry.register(AnotherPlugin())
    assert registry.get_plugin("dummy") is not None
    assert registry.get_plugin("another") is not None


def test_get_plugin_unknown_returns_none(registry):
    assert registry.get_plugin("nonexistent") is None


def test_all_plugins_property(registry):
    registry.register(DummyPlugin())
    registry.register(AnotherPlugin())
    assert set(registry.all_plugins.keys()) == {"dummy", "another"}


# ---------------------------------------------------------------------------
# Bundled plugin loading
# ---------------------------------------------------------------------------

def test_load_bundled_empty_list_returns_zero(registry):
    # BUNDLED_PLUGINS is empty by default; should load zero plugins
    count = registry.load_bundled()
    assert count == 0


def test_load_bundled_skips_bad_module(registry, caplog):
    # Temporarily inject a bad module name so we can test error handling
    import murmurate.plugins.registry as reg_mod
    original = reg_mod.BUNDLED_PLUGINS[:]
    reg_mod.BUNDLED_PLUGINS.append("murmurate.plugins._does_not_exist_xyz")
    try:
        with caplog.at_level("WARNING"):
            count = registry.load_bundled()
        assert count == 0
        assert any("_does_not_exist_xyz" in r.message for r in caplog.records)
    finally:
        reg_mod.BUNDLED_PLUGINS[:] = original


# ---------------------------------------------------------------------------
# User plugin loading
# ---------------------------------------------------------------------------

VALID_PLUGIN_SOURCE = textwrap.dedent("""\
    from murmurate.plugins.base import SitePlugin
    from murmurate.models import TransportType

    class UserPlugin(SitePlugin):
        @property
        def name(self):
            return "userplugin"

        @property
        def domains(self):
            return ["user.example.com"]

        @property
        def preferred_transport(self):
            return TransportType.HTTP

        @property
        def rate_limit_rpm(self):
            return 20

        async def execute_search(self, context, transport):
            return []

        async def browse_result(self, result, context, transport):
            raise NotImplementedError
""")


def test_load_user_plugins_discovers_valid_plugin(registry, tmp_path):
    plugin_file = tmp_path / "userplugin.py"
    plugin_file.write_text(VALID_PLUGIN_SOURCE)

    count = registry.load_user_plugins(tmp_path)

    assert count == 1
    assert registry.get_plugin("userplugin") is not None


def test_load_user_plugins_skips_underscore_files(registry, tmp_path):
    hidden = tmp_path / "_private.py"
    hidden.write_text(VALID_PLUGIN_SOURCE)

    count = registry.load_user_plugins(tmp_path)
    assert count == 0


def test_load_user_plugins_nonexistent_dir_returns_zero(registry):
    count = registry.load_user_plugins(Path("/tmp/murmurate_no_such_dir_xyz"))
    assert count == 0


def test_load_user_plugins_bad_file_logs_warning(registry, tmp_path, caplog):
    bad_file = tmp_path / "broken.py"
    bad_file.write_text("this is not valid python !!!")

    with caplog.at_level("WARNING"):
        count = registry.load_user_plugins(tmp_path)

    assert count == 0
    assert any("broken.py" in r.message for r in caplog.records)


def test_load_user_plugins_returns_zero_for_empty_dir(registry, tmp_path):
    assert registry.load_user_plugins(tmp_path) == 0


# ---------------------------------------------------------------------------
# get_enabled
# ---------------------------------------------------------------------------

def test_get_enabled_returns_all_registered(registry):
    registry.register(DummyPlugin())
    registry.register(AnotherPlugin())
    enabled = registry.get_enabled()
    names = {p.name for p in enabled}
    assert names == {"dummy", "another"}


def test_get_enabled_excludes_disabled(registry):
    registry.register(DummyPlugin())
    registry.register(AnotherPlugin())
    registry.disable("dummy")
    enabled = registry.get_enabled()
    assert all(p.name != "dummy" for p in enabled)
    assert any(p.name == "another" for p in enabled)


def test_get_enabled_filters_by_name_list(registry):
    registry.register(DummyPlugin())
    registry.register(AnotherPlugin())
    enabled = registry.get_enabled(enabled_names=["dummy"])
    assert len(enabled) == 1
    assert enabled[0].name == "dummy"


def test_get_enabled_name_filter_excludes_unknown(registry):
    registry.register(DummyPlugin())
    enabled = registry.get_enabled(enabled_names=["nonexistent"])
    assert enabled == []


def test_get_enabled_empty_registry(registry):
    assert registry.get_enabled() == []


# ---------------------------------------------------------------------------
# Manual disable / enable
# ---------------------------------------------------------------------------

def test_disable_prevents_plugin_from_appearing(registry_with_dummy):
    registry_with_dummy.disable("dummy")
    assert registry_with_dummy.get_enabled() == []


def test_enable_restores_disabled_plugin(registry_with_dummy):
    registry_with_dummy.disable("dummy")
    registry_with_dummy.enable("dummy")
    enabled = registry_with_dummy.get_enabled()
    assert len(enabled) == 1
    assert enabled[0].name == "dummy"


def test_enable_resets_failure_count(registry_with_dummy):
    for _ in range(3):
        registry_with_dummy.record_failure("dummy")
    registry_with_dummy.enable("dummy")
    info = registry_with_dummy.get_plugin_info("dummy")
    assert info["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# Failure tracking and auto-disable
# ---------------------------------------------------------------------------

def test_record_failure_increments_count(registry_with_dummy):
    registry_with_dummy.record_failure("dummy")
    info = registry_with_dummy.get_plugin_info("dummy")
    assert info["consecutive_failures"] == 1


def test_record_success_resets_failure_count(registry_with_dummy):
    for _ in range(3):
        registry_with_dummy.record_failure("dummy")
    registry_with_dummy.record_success("dummy")
    info = registry_with_dummy.get_plugin_info("dummy")
    assert info["consecutive_failures"] == 0


def test_auto_disable_at_threshold(registry_with_dummy):
    for _ in range(5):
        registry_with_dummy.record_failure("dummy")
    assert registry_with_dummy.get_enabled() == []
    info = registry_with_dummy.get_plugin_info("dummy")
    assert info["enabled"] is False


def test_auto_disable_not_triggered_below_threshold(registry_with_dummy):
    for _ in range(4):
        registry_with_dummy.record_failure("dummy")
    assert len(registry_with_dummy.get_enabled()) == 1


def test_auto_disable_logs_warning(registry_with_dummy, caplog):
    with caplog.at_level("WARNING"):
        for _ in range(5):
            registry_with_dummy.record_failure("dummy")
    assert any("dummy" in r.message and "auto-disabled" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Cooldown / re-enable after auto-disable
# ---------------------------------------------------------------------------

def test_auto_disabled_plugin_re_enables_after_cooldown(registry_with_dummy):
    """Plugin that was auto-disabled should reappear once the cooldown elapses."""
    with patch("time.monotonic") as mock_mono:
        # Trigger auto-disable at t=100
        mock_mono.return_value = 100.0
        for _ in range(5):
            registry_with_dummy.record_failure("dummy")

        # Still within cooldown (t=200, only 100s elapsed, threshold is 300s)
        mock_mono.return_value = 200.0
        assert registry_with_dummy.get_enabled() == []

        # Past cooldown (t=410, 310s elapsed)
        mock_mono.return_value = 410.0
        enabled = registry_with_dummy.get_enabled()
        assert len(enabled) == 1
        assert enabled[0].name == "dummy"


def test_cooldown_resets_failure_count(registry_with_dummy):
    """After cooldown, failure count should be reset to zero."""
    with patch("time.monotonic") as mock_mono:
        mock_mono.return_value = 100.0
        for _ in range(5):
            registry_with_dummy.record_failure("dummy")

        mock_mono.return_value = 410.0
        registry_with_dummy.get_enabled()  # triggers the cooldown check

    info = registry_with_dummy.get_plugin_info("dummy")
    assert info["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# get_plugin_info
# ---------------------------------------------------------------------------

def test_get_plugin_info_correct_fields(registry_with_dummy):
    info = registry_with_dummy.get_plugin_info("dummy")
    assert info["name"] == "dummy"
    assert info["domains"] == ["dummy.example.com"]
    assert info["preferred_transport"] == "http"
    assert info["rate_limit_rpm"] == 30
    assert info["enabled"] is True
    assert info["consecutive_failures"] == 0


def test_get_plugin_info_reflects_disabled_state(registry_with_dummy):
    registry_with_dummy.disable("dummy")
    info = registry_with_dummy.get_plugin_info("dummy")
    assert info["enabled"] is False


def test_get_plugin_info_unknown_returns_none(registry):
    assert registry.get_plugin_info("does_not_exist") is None
