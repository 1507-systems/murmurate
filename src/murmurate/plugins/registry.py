"""
plugins/registry.py — Plugin discovery, registration, and health tracking.

The PluginRegistry is the single source of truth for which plugins are
available and which are currently active. It handles three concerns:

  1. Discovery — bundled plugins are imported by module name; user plugins
     are loaded from .py files in a configured directory. Both paths use
     introspection to find concrete SitePlugin subclasses automatically, so
     adding a new plugin is as simple as dropping a file in the right place.

  2. Routing — get_enabled() returns the plugins that are currently active,
     optionally filtered by an explicit allow-list. The scheduler calls this
     to decide which plugins to include in a session.

  3. Health tracking — the registry counts consecutive failures per plugin
     and auto-disables any plugin that exceeds the threshold. After a
     cooldown period the plugin is re-enabled transparently, so transient
     network issues don't require manual intervention.
"""

import importlib
import importlib.util
import logging
import time
from pathlib import Path

from murmurate.plugins.base import SitePlugin

logger = logging.getLogger(__name__)

# List of bundled plugin module paths. Add entries here as plugins are built.
# Each module must contain at least one concrete SitePlugin subclass.
BUNDLED_PLUGINS: list[str] = [
    # "murmurate.plugins.duckduckgo",  # Added in Task 14
    # "murmurate.plugins.wikipedia",   # Added in Task 14
]


class PluginRegistry:
    """Discovers, manages, and tracks health of site plugins."""

    def __init__(self) -> None:
        # Primary plugin store: name -> instance
        self._plugins: dict[str, SitePlugin] = {}
        # Consecutive failure counts per plugin name
        self._failure_counts: dict[str, int] = {}
        # Names that are currently disabled (manually or auto)
        self._disabled: set[str] = set()
        # monotonic timestamp of when each plugin was auto-disabled (manual
        # disables do NOT get an entry here, so cooldown doesn't apply to them)
        self._disabled_at: dict[str, float] = {}

        # Auto-disable after this many consecutive failures
        self._auto_disable_threshold: int = 5
        # How long (seconds) before an auto-disabled plugin is re-tried
        self._cooldown_s: float = 300.0

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, plugin: SitePlugin) -> None:
        """Register a plugin instance. Overwrites any existing entry by name."""
        self._plugins[plugin.name] = plugin
        # Initialise failure count without disturbing an existing entry
        # (re-registering after a reload shouldn't reset a live failure streak)
        self._failure_counts.setdefault(plugin.name, 0)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def load_bundled(self) -> int:
        """
        Import and register all bundled plugins listed in BUNDLED_PLUGINS.

        Skips modules that fail to import and logs a warning instead of
        raising, so a broken plugin never prevents the others from loading.

        Returns the number of plugin instances successfully registered.
        """
        count = 0
        for module_name in BUNDLED_PLUGINS:
            try:
                mod = importlib.import_module(module_name)
                count += self._register_from_module(mod)
            except Exception as e:
                logger.warning(f"Failed to load bundled plugin {module_name}: {e}")
        return count

    def load_user_plugins(self, plugin_dir: Path) -> int:
        """
        Load .py files from a user-supplied plugin directory.

        Files whose names start with '_' (e.g. __init__.py, _helpers.py) are
        skipped so the directory can contain supporting code without it being
        treated as a plugin. Import errors are logged and do not abort the
        scan.

        Returns the number of plugin instances successfully registered.
        """
        if not plugin_dir.is_dir():
            return 0

        count = 0
        for py_file in sorted(plugin_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                count += self._register_from_module(mod)
            except Exception as e:
                logger.warning(f"Failed to load user plugin {py_file}: {e}")
        return count

    def _register_from_module(self, mod) -> int:
        """
        Inspect a module for concrete SitePlugin subclasses and register them.

        A class qualifies if it is a proper subclass of SitePlugin (i.e. not
        SitePlugin itself) and is not abstract. Each qualifying class is
        instantiated with no arguments and registered.
        """
        import inspect

        count = 0
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, SitePlugin)
                and attr is not SitePlugin
                and not inspect.isabstract(attr)
            ):
                self.register(attr())
                count += 1
        return count

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get_enabled(self, enabled_names: list[str] | None = None) -> list[SitePlugin]:
        """
        Return currently-active plugins.

        Disabled plugins are excluded. Auto-disabled plugins whose cooldown
        has elapsed are silently re-enabled before the list is built, so
        callers never have to manage cooldowns manually.

        If enabled_names is provided, only plugins whose name appears in that
        list are returned (in addition to the enabled check). Passing an empty
        list will always return an empty result.
        """
        now = time.monotonic()
        result = []

        for name, plugin in self._plugins.items():
            if name in self._disabled:
                # Check whether this is an auto-disable with an elapsed cooldown
                if name in self._disabled_at:
                    elapsed = now - self._disabled_at[name]
                    if elapsed >= self._cooldown_s:
                        # Cooldown expired — transparently re-enable
                        self._disabled.discard(name)
                        del self._disabled_at[name]
                        self._failure_counts[name] = 0
                    else:
                        continue  # Still in cooldown, skip
                else:
                    # Manual disable — no cooldown applies
                    continue

            if enabled_names is not None and name not in enabled_names:
                continue

            result.append(plugin)

        return result

    def get_plugin(self, name: str) -> SitePlugin | None:
        """Return the plugin instance for the given name, or None."""
        return self._plugins.get(name)

    def get_plugin_info(self, name: str) -> dict | None:
        """
        Return a serialisable summary of a plugin's current state.

        Returns None if no plugin with that name is registered. The 'enabled'
        field reflects whether the plugin would appear in get_enabled() right
        now (i.e. it accounts for manual disables and unexpired cooldowns, but
        NOT for any enabled_names filter that a caller might pass).
        """
        plugin = self._plugins.get(name)
        if plugin is None:
            return None
        return {
            "name": plugin.name,
            "domains": plugin.domains,
            "preferred_transport": plugin.preferred_transport.value,
            "rate_limit_rpm": plugin.rate_limit_rpm,
            "enabled": name not in self._disabled,
            "consecutive_failures": self._failure_counts.get(name, 0),
        }

    @property
    def all_plugins(self) -> dict[str, SitePlugin]:
        """Return a shallow copy of the full plugin map (name -> instance)."""
        return dict(self._plugins)

    # ------------------------------------------------------------------
    # Health tracking
    # ------------------------------------------------------------------

    def record_failure(self, plugin_name: str) -> None:
        """
        Record a consecutive failure for the named plugin.

        If the failure count reaches the auto-disable threshold the plugin is
        disabled immediately and a warning is logged. The failure count for
        unknown plugin names is tracked in case the plugin is registered later.
        """
        self._failure_counts[plugin_name] = self._failure_counts.get(plugin_name, 0) + 1
        if self._failure_counts[plugin_name] >= self._auto_disable_threshold:
            self._disabled.add(plugin_name)
            self._disabled_at[plugin_name] = time.monotonic()
            logger.warning(
                f"Plugin {plugin_name} auto-disabled after "
                f"{self._auto_disable_threshold} consecutive failures"
            )

    def record_success(self, plugin_name: str) -> None:
        """Reset the consecutive-failure counter for the named plugin."""
        self._failure_counts[plugin_name] = 0

    # ------------------------------------------------------------------
    # Manual enable / disable
    # ------------------------------------------------------------------

    def disable(self, plugin_name: str) -> None:
        """
        Manually disable a plugin.

        Unlike auto-disable, manual disables have no cooldown — the plugin
        stays off until enable() is explicitly called.
        """
        self._disabled.add(plugin_name)
        # Do NOT set _disabled_at here; absence of that key signals manual disable

    def enable(self, plugin_name: str) -> None:
        """
        Re-enable a disabled plugin (manual or auto-disabled).

        Also resets the failure counter so the plugin starts fresh.
        """
        self._disabled.discard(plugin_name)
        self._disabled_at.pop(plugin_name, None)
        self._failure_counts[plugin_name] = 0
