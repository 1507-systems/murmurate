#!/usr/bin/env python3
"""
murmurate_menubar.py — macOS menu bar app for Murmurate control.

Uses rumps (Ridiculously Uncomplicated macOS Python Statusbar apps) to provide
a lightweight tray icon with:
  - Live daemon status polling (running / stopped / error)
  - Session counts (today's completed / failed)
  - Persona list with session counts
  - Quick controls: stop daemon, open web dashboard
  - Configurable API endpoint and auth token

The menu bar app connects to the Murmurate REST API (default: http://127.0.0.1:7683/api)
and polls every 10 seconds for status updates.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field

import rumps


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default API endpoint — matches `murmurate start --api` defaults
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 7683

# How often to poll the API for status updates (seconds)
POLL_INTERVAL = 10

# Status symbols for the menu bar title
STATUS_SYMBOLS = {
    "running": "\u25B6",    # Black right-pointing triangle
    "stopped": "\u25A0",    # Black square
    "error":   "\u26A0",    # Warning sign
}


@dataclass
class AppConfig:
    """Persistent configuration for the menu bar app."""
    api_host: str = DEFAULT_API_HOST
    api_port: int = DEFAULT_API_PORT
    api_token: str | None = None
    poll_interval: int = POLL_INTERVAL

    @property
    def base_url(self) -> str:
        return f"http://{self.api_host}:{self.api_port}/api"

    @property
    def dashboard_url(self) -> str:
        return f"http://{self.api_host}:{self.api_port}"


@dataclass
class DaemonStatus:
    """Parsed status response from the API."""
    connected: bool = False
    running: bool = False
    version: str = "?"
    config_dir: str = ""
    sessions_today: int = 0
    sessions_completed: int = 0
    sessions_failed: int = 0
    error_message: str = ""


@dataclass
class PersonaSummary:
    """Minimal persona info for display in the menu."""
    name: str = ""
    total_sessions: int = 0
    topic_count: int = 0
    seeds: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# API Client (synchronous, runs in background thread)
# ---------------------------------------------------------------------------

class ApiClient:
    """Simple synchronous HTTP client for the Murmurate REST API.

    Uses urllib instead of aiohttp/requests to avoid adding dependencies beyond
    rumps. All methods are blocking and designed to be called from a timer
    callback or background thread.
    """

    def __init__(self, config: AppConfig):
        self.config = config

    def _request(self, path: str, method: str = "GET", body: dict | None = None) -> dict:
        """Make an HTTP request to the API and return parsed JSON."""
        url = f"{self.config.base_url}{path}"
        data = json.dumps(body).encode() if body else None
        headers = {"Content-Type": "application/json"}

        if self.config.api_token:
            headers["Authorization"] = f"Bearer {self.config.api_token}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())

    def get_status(self) -> DaemonStatus:
        """Fetch daemon status. Returns a DaemonStatus even on failure."""
        try:
            data = self._request("/status")
            return DaemonStatus(
                connected=True,
                running=data.get("running", False),
                version=data.get("version", "?"),
                config_dir=data.get("config_dir", ""),
                sessions_today=data.get("sessions_today", 0),
                sessions_completed=data.get("sessions_completed_today", 0),
                sessions_failed=data.get("sessions_failed_today", 0),
            )
        except urllib.error.URLError as exc:
            return DaemonStatus(
                connected=False,
                error_message=f"Connection refused: {exc.reason}",
            )
        except Exception as exc:
            return DaemonStatus(
                connected=False,
                error_message=str(exc),
            )

    def get_personas(self) -> list[PersonaSummary]:
        """Fetch persona list. Returns empty list on failure."""
        try:
            data = self._request("/personas")
            return [
                PersonaSummary(
                    name=p.get("name", ""),
                    total_sessions=p.get("total_sessions", 0),
                    topic_count=p.get("topic_count", 0),
                    seeds=p.get("seeds", []),
                )
                for p in data
            ]
        except Exception:
            return []

    def stop_daemon(self) -> str:
        """Send stop signal. Returns message string."""
        try:
            data = self._request("/daemon/stop", method="POST")
            return data.get("message", "Stop signal sent")
        except Exception as exc:
            return f"Failed: {exc}"

    def get_history(self, limit: int = 5) -> list[dict]:
        """Fetch recent session history."""
        try:
            return self._request(f"/history?limit={limit}")
        except Exception:
            return []

    def get_stats(self) -> dict:
        """Fetch activity statistics."""
        try:
            return self._request("/stats")
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Menu Bar Application
# ---------------------------------------------------------------------------

class MurmurateMenuBar(rumps.App):
    """macOS menu bar application for Murmurate daemon control.

    Displays a status icon and provides quick access to:
    - Daemon status (running/stopped/error) with session counts
    - Persona list with session history
    - Stop daemon control
    - Link to web dashboard
    - API connection settings
    """

    def __init__(self):
        super().__init__(
            name="Murmurate",
            title=f"{STATUS_SYMBOLS['stopped']} Murmurate",
            quit_button=None,  # We add our own quit button at the bottom
        )

        self.config = AppConfig()
        self._load_config_from_env()
        self.client = ApiClient(self.config)
        self.status = DaemonStatus()
        self.personas: list[PersonaSummary] = []

        # Build initial menu structure
        self._build_menu()

    def _load_config_from_env(self):
        """Load configuration from environment variables if set.

        Supports:
            MURMURATE_API_HOST — API host (default: 127.0.0.1)
            MURMURATE_API_PORT — API port (default: 7683)
            MURMURATE_API_TOKEN — Bearer token for auth
            MURMURATE_POLL_INTERVAL — Poll interval in seconds (default: 10)
        """
        if host := os.environ.get("MURMURATE_API_HOST"):
            self.config.api_host = host
        if port := os.environ.get("MURMURATE_API_PORT"):
            try:
                self.config.api_port = int(port)
            except ValueError:
                pass
        if token := os.environ.get("MURMURATE_API_TOKEN"):
            self.config.api_token = token
        if interval := os.environ.get("MURMURATE_POLL_INTERVAL"):
            try:
                self.config.poll_interval = max(1, int(interval))
            except ValueError:
                pass

    def _build_menu(self):
        """Construct the full menu hierarchy."""
        # Status section — these get updated by the timer
        self.status_item = rumps.MenuItem("Status: Checking...")
        self.status_item.set_callback(None)

        self.version_item = rumps.MenuItem("Version: ?")
        self.version_item.set_callback(None)

        self.sessions_item = rumps.MenuItem("Sessions today: --")
        self.sessions_item.set_callback(None)

        # Personas submenu
        self.personas_menu = rumps.MenuItem("Personas")
        self.personas_loading = rumps.MenuItem("Loading...")
        self.personas_loading.set_callback(None)
        self.personas_menu.add(self.personas_loading)

        # Recent sessions submenu
        self.recent_menu = rumps.MenuItem("Recent Sessions")
        self.recent_loading = rumps.MenuItem("Loading...")
        self.recent_loading.set_callback(None)
        self.recent_menu.add(self.recent_loading)

        # Controls
        self.open_dashboard_item = rumps.MenuItem(
            "Open Dashboard", callback=self._open_dashboard
        )
        self.stop_daemon_item = rumps.MenuItem(
            "Stop Daemon", callback=self._stop_daemon
        )

        # Connection settings
        self.connection_item = rumps.MenuItem(
            f"API: {self.config.api_host}:{self.config.api_port}"
        )
        self.connection_item.set_callback(None)

        self.configure_item = rumps.MenuItem(
            "Configure Connection...", callback=self._configure_connection
        )

        # Quit
        self.quit_item = rumps.MenuItem("Quit", callback=self._quit)

        # Assemble menu
        self.menu = [
            self.status_item,
            self.version_item,
            self.sessions_item,
            None,  # separator
            self.personas_menu,
            self.recent_menu,
            None,  # separator
            self.open_dashboard_item,
            self.stop_daemon_item,
            None,  # separator
            self.connection_item,
            self.configure_item,
            None,  # separator
            self.quit_item,
        ]

    @rumps.timer(POLL_INTERVAL)
    def _poll_status(self, _sender):
        """Timer callback that polls the API for current daemon status.

        Runs every POLL_INTERVAL seconds. Updates the menu bar icon, status
        text, session counts, and persona list.
        """
        # Run API calls in a background thread to avoid blocking the main thread
        thread = threading.Thread(target=self._fetch_and_update, daemon=True)
        thread.start()

    def _fetch_and_update(self):
        """Fetch status and personas from API, then update UI on main thread."""
        status = self.client.get_status()
        personas = self.client.get_personas() if status.connected else []
        history = self.client.get_history(limit=5) if status.connected else []

        # Schedule UI update on the main thread via rumps timer mechanism
        self._apply_status_update(status, personas, history)

    def _apply_status_update(
        self,
        status: DaemonStatus,
        personas: list[PersonaSummary],
        history: list[dict],
    ):
        """Apply fetched data to the menu UI elements."""
        self.status = status
        self.personas = personas

        # Update menu bar title with status symbol
        if not status.connected:
            symbol = STATUS_SYMBOLS["error"]
            self.title = f"{symbol} Murmurate"
            self.status_item.title = "Status: Disconnected"
        elif status.running:
            symbol = STATUS_SYMBOLS["running"]
            self.title = f"{symbol} Murmurate"
            self.status_item.title = "Status: Running"
        else:
            symbol = STATUS_SYMBOLS["stopped"]
            self.title = f"{symbol} Murmurate"
            self.status_item.title = "Status: Stopped (API only)"

        # Version
        if status.connected:
            self.version_item.title = f"Version: {status.version}"
        else:
            self.version_item.title = "Version: --"

        # Session counts
        if status.connected:
            completed = status.sessions_completed
            failed = status.sessions_failed
            total = status.sessions_today
            self.sessions_item.title = (
                f"Sessions today: {total} ({completed} ok, {failed} failed)"
            )
        else:
            self.sessions_item.title = "Sessions today: --"

        # Enable/disable controls based on connection state
        self.stop_daemon_item.set_callback(
            self._stop_daemon if status.connected and status.running else None
        )
        self.open_dashboard_item.set_callback(
            self._open_dashboard if status.connected else None
        )

        # Update personas submenu
        self._update_personas_menu(personas)

        # Update recent sessions submenu
        self._update_recent_menu(history)

        # Update connection display
        self.connection_item.title = (
            f"API: {self.config.api_host}:{self.config.api_port}"
        )

    def _update_personas_menu(self, personas: list[PersonaSummary]):
        """Rebuild the Personas submenu with current persona data."""
        self.personas_menu.clear()

        if not personas:
            empty = rumps.MenuItem("No personas" if self.status.connected else "Disconnected")
            empty.set_callback(None)
            self.personas_menu.add(empty)
            return

        for p in personas:
            seeds_str = ", ".join(p.seeds[:3])
            if len(p.seeds) > 3:
                seeds_str += "..."
            label = f"{p.name}  ({p.total_sessions} sessions, {p.topic_count} topics)"
            item = rumps.MenuItem(label)
            item.set_callback(None)
            self.personas_menu.add(item)

            # Sub-items showing seeds
            if seeds_str:
                seed_item = rumps.MenuItem(f"  Seeds: {seeds_str}")
                seed_item.set_callback(None)
                self.personas_menu.add(seed_item)

    def _update_recent_menu(self, history: list[dict]):
        """Rebuild the Recent Sessions submenu with latest session data."""
        self.recent_menu.clear()

        if not history:
            empty = rumps.MenuItem(
                "No sessions" if self.status.connected else "Disconnected"
            )
            empty.set_callback(None)
            self.recent_menu.add(empty)
            return

        for session in history:
            persona = session.get("persona", "?")
            plugin = session.get("plugin", "?")
            status_str = session.get("status", "?")
            started = session.get("started_at", "")
            # Trim ISO timestamp to just time portion for readability
            time_str = started.split("T")[1][:8] if "T" in started else started[:19]

            status_icon = "\u2713" if status_str == "completed" else "\u2717"  # check / cross
            label = f"{status_icon} {time_str}  {persona} / {plugin}"
            item = rumps.MenuItem(label)
            item.set_callback(None)
            self.recent_menu.add(item)

    # -----------------------------------------------------------------------
    # Callbacks
    # -----------------------------------------------------------------------

    def _open_dashboard(self, _sender):
        """Open the web dashboard in the default browser."""
        webbrowser.open(self.config.dashboard_url)

    def _stop_daemon(self, _sender):
        """Send stop signal to the daemon after confirmation."""
        response = rumps.alert(
            title="Stop Murmurate Daemon",
            message="Are you sure you want to stop the Murmurate daemon?",
            ok="Stop",
            cancel="Cancel",
        )
        if response == 1:  # OK pressed
            result = self.client.stop_daemon()
            rumps.notification(
                title="Murmurate",
                subtitle="Daemon Control",
                message=result,
            )

    def _configure_connection(self, _sender):
        """Show a dialog to configure the API connection endpoint."""
        current = f"{self.config.api_host}:{self.config.api_port}"
        window = rumps.Window(
            title="Configure Murmurate Connection",
            message=(
                "Enter the API endpoint (host:port).\n"
                "Default: 127.0.0.1:7683\n\n"
                "You can also set the MURMURATE_API_TOKEN\n"
                "environment variable for authentication."
            ),
            default_text=current,
            ok="Save",
            cancel="Cancel",
            dimensions=(300, 24),
        )
        response = window.run()

        if response.clicked == 1:  # OK
            text = response.text.strip()
            if ":" in text:
                parts = text.rsplit(":", 1)
                self.config.api_host = parts[0]
                try:
                    self.config.api_port = int(parts[1])
                except ValueError:
                    rumps.alert(
                        title="Invalid Port",
                        message=f"'{parts[1]}' is not a valid port number.",
                    )
                    return
            else:
                self.config.api_host = text

            # Recreate client with new config
            self.client = ApiClient(self.config)

            # Update connection display
            self.connection_item.title = (
                f"API: {self.config.api_host}:{self.config.api_port}"
            )

            # Force an immediate status refresh
            thread = threading.Thread(target=self._fetch_and_update, daemon=True)
            thread.start()

    def _quit(self, _sender):
        """Quit the menu bar app (does not stop the daemon)."""
        rumps.quit_application()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Launch the Murmurate menu bar application."""
    app = MurmurateMenuBar()
    app.run()


if __name__ == "__main__":
    main()
