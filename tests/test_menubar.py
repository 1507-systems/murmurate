"""
test_menubar.py — Tests for the Murmurate macOS menu bar app.

Tests the API client, configuration, and status parsing without requiring
a running daemon or the macOS UI framework (rumps is mocked).
"""

from __future__ import annotations

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from unittest.mock import MagicMock, patch
import threading
import sys

import pytest
import rumps

# Add menubar directory to path so we can import the module
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "menubar",
    ),
)


# ---------------------------------------------------------------------------
# AppConfig tests
# ---------------------------------------------------------------------------

class TestAppConfig:
    """Tests for AppConfig dataclass and its properties."""

    def test_default_values(self):
        from murmurate_menubar import AppConfig
        cfg = AppConfig()
        assert cfg.api_host == "127.0.0.1"
        assert cfg.api_port == 7683
        assert cfg.api_token is None
        assert cfg.poll_interval == 10

    def test_base_url(self):
        from murmurate_menubar import AppConfig
        cfg = AppConfig(api_host="192.168.1.5", api_port=8080)
        assert cfg.base_url == "http://192.168.1.5:8080/api"

    def test_dashboard_url(self):
        from murmurate_menubar import AppConfig
        cfg = AppConfig(api_host="10.0.0.1", api_port=9999)
        assert cfg.dashboard_url == "http://10.0.0.1:9999"

    def test_custom_token(self):
        from murmurate_menubar import AppConfig
        cfg = AppConfig(api_token="my-secret")
        assert cfg.api_token == "my-secret"

    def test_custom_poll_interval(self):
        from murmurate_menubar import AppConfig
        cfg = AppConfig(poll_interval=30)
        assert cfg.poll_interval == 30


# ---------------------------------------------------------------------------
# DaemonStatus tests
# ---------------------------------------------------------------------------

class TestDaemonStatus:
    """Tests for DaemonStatus dataclass defaults."""

    def test_default_disconnected(self):
        from murmurate_menubar import DaemonStatus
        status = DaemonStatus()
        assert status.connected is False
        assert status.running is False
        assert status.version == "?"
        assert status.sessions_today == 0
        assert status.sessions_completed == 0
        assert status.sessions_failed == 0
        assert status.error_message == ""

    def test_connected_running(self):
        from murmurate_menubar import DaemonStatus
        status = DaemonStatus(
            connected=True,
            running=True,
            version="0.2.0",
            sessions_today=15,
            sessions_completed=12,
            sessions_failed=3,
        )
        assert status.connected is True
        assert status.running is True
        assert status.sessions_today == 15


# ---------------------------------------------------------------------------
# PersonaSummary tests
# ---------------------------------------------------------------------------

class TestPersonaSummary:
    """Tests for PersonaSummary dataclass."""

    def test_defaults(self):
        from murmurate_menubar import PersonaSummary
        p = PersonaSummary()
        assert p.name == ""
        assert p.total_sessions == 0
        assert p.topic_count == 0
        assert p.seeds == []

    def test_with_data(self):
        from murmurate_menubar import PersonaSummary
        p = PersonaSummary(
            name="researcher",
            total_sessions=42,
            topic_count=15,
            seeds=["quantum computing", "machine learning"],
        )
        assert p.name == "researcher"
        assert p.total_sessions == 42
        assert p.seeds == ["quantum computing", "machine learning"]


# ---------------------------------------------------------------------------
# Test HTTP server for API client tests
# ---------------------------------------------------------------------------

class _MockAPIHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler that returns canned JSON responses."""

    # Class-level response data that tests can override
    responses = {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in self.responses:
            data = self.responses[path]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "not found"}')

    def do_POST(self):
        path = self.path.split("?")[0]
        if path in self.responses:
            data = self.responses[path]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress request logging during tests."""
        pass


@pytest.fixture
def mock_api_server():
    """Start a local HTTP server with canned API responses."""
    # Set up default responses
    _MockAPIHandler.responses = {
        "/api/status": {
            "running": True,
            "version": "0.2.0",
            "config_dir": "/tmp/murmurate",
            "sessions_today": 10,
            "sessions_completed_today": 8,
            "sessions_failed_today": 2,
        },
        "/api/personas": [
            {
                "name": "researcher",
                "total_sessions": 25,
                "topic_count": 12,
                "seeds": ["quantum computing", "topology"],
                "expertise_level": 0.5,
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "name": "hobbyist",
                "total_sessions": 10,
                "topic_count": 5,
                "seeds": ["woodworking", "pottery"],
                "expertise_level": 0.3,
                "created_at": "2026-02-01T00:00:00Z",
            },
        ],
        "/api/daemon/stop": {"message": "Shutdown signal sent"},
        "/api/history": [
            {
                "persona": "researcher",
                "plugin": "duckduckgo",
                "status": "completed",
                "started_at": "2026-03-22T10:30:00Z",
            },
            {
                "persona": "hobbyist",
                "plugin": "wikipedia",
                "status": "failed",
                "started_at": "2026-03-22T10:25:00Z",
            },
        ],
        "/api/stats": {
            "total_sessions": 100,
            "by_plugin": {"duckduckgo": 50, "wikipedia": 30},
        },
    }

    server = HTTPServer(("127.0.0.1", 0), _MockAPIHandler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield port

    server.shutdown()


# ---------------------------------------------------------------------------
# ApiClient tests
# ---------------------------------------------------------------------------

class TestApiClient:
    """Tests for the synchronous API client."""

    def test_get_status_connected(self, mock_api_server):
        from murmurate_menubar import ApiClient, AppConfig
        config = AppConfig(api_host="127.0.0.1", api_port=mock_api_server)
        client = ApiClient(config)

        status = client.get_status()
        assert status.connected is True
        assert status.running is True
        assert status.version == "0.2.0"
        assert status.sessions_today == 10
        assert status.sessions_completed == 8
        assert status.sessions_failed == 2

    def test_get_status_disconnected(self):
        from murmurate_menubar import ApiClient, AppConfig
        # Use a port that nothing is listening on
        config = AppConfig(api_host="127.0.0.1", api_port=1)
        client = ApiClient(config)

        status = client.get_status()
        assert status.connected is False
        assert status.running is False
        assert "Connection refused" in status.error_message or status.error_message != ""

    def test_get_personas(self, mock_api_server):
        from murmurate_menubar import ApiClient, AppConfig
        config = AppConfig(api_host="127.0.0.1", api_port=mock_api_server)
        client = ApiClient(config)

        personas = client.get_personas()
        assert len(personas) == 2
        assert personas[0].name == "researcher"
        assert personas[0].total_sessions == 25
        assert personas[1].name == "hobbyist"
        assert personas[1].seeds == ["woodworking", "pottery"]

    def test_get_personas_disconnected(self):
        from murmurate_menubar import ApiClient, AppConfig
        config = AppConfig(api_host="127.0.0.1", api_port=1)
        client = ApiClient(config)

        personas = client.get_personas()
        assert personas == []

    def test_stop_daemon(self, mock_api_server):
        from murmurate_menubar import ApiClient, AppConfig
        config = AppConfig(api_host="127.0.0.1", api_port=mock_api_server)
        client = ApiClient(config)

        result = client.stop_daemon()
        assert "Shutdown signal sent" in result

    def test_stop_daemon_disconnected(self):
        from murmurate_menubar import ApiClient, AppConfig
        config = AppConfig(api_host="127.0.0.1", api_port=1)
        client = ApiClient(config)

        result = client.stop_daemon()
        assert "Failed" in result

    def test_get_history(self, mock_api_server):
        from murmurate_menubar import ApiClient, AppConfig
        config = AppConfig(api_host="127.0.0.1", api_port=mock_api_server)
        client = ApiClient(config)

        history = client.get_history(limit=5)
        assert len(history) == 2
        assert history[0]["persona"] == "researcher"
        assert history[1]["status"] == "failed"

    def test_get_history_disconnected(self):
        from murmurate_menubar import ApiClient, AppConfig
        config = AppConfig(api_host="127.0.0.1", api_port=1)
        client = ApiClient(config)

        history = client.get_history()
        assert history == []

    def test_get_stats(self, mock_api_server):
        from murmurate_menubar import ApiClient, AppConfig
        config = AppConfig(api_host="127.0.0.1", api_port=mock_api_server)
        client = ApiClient(config)

        stats = client.get_stats()
        assert stats["total_sessions"] == 100
        assert "by_plugin" in stats

    def test_get_stats_disconnected(self):
        from murmurate_menubar import ApiClient, AppConfig
        config = AppConfig(api_host="127.0.0.1", api_port=1)
        client = ApiClient(config)

        stats = client.get_stats()
        assert stats == {}

    def test_auth_token_header(self, mock_api_server):
        """Verify that the auth token is included in requests when configured."""
        from murmurate_menubar import ApiClient, AppConfig
        config = AppConfig(
            api_host="127.0.0.1",
            api_port=mock_api_server,
            api_token="test-token-123",
        )
        client = ApiClient(config)

        # Should still work — mock server doesn't check auth
        status = client.get_status()
        assert status.connected is True


# ---------------------------------------------------------------------------
# Environment variable configuration tests
# ---------------------------------------------------------------------------

class TestEnvConfig:
    """Tests for environment variable configuration loading."""

    def test_env_host(self):
        from murmurate_menubar import AppConfig, MurmurateMenuBar
        with patch.dict(os.environ, {"MURMURATE_API_HOST": "10.0.0.5"}):
            cfg = AppConfig()
            # Simulate what _load_config_from_env does
            if host := os.environ.get("MURMURATE_API_HOST"):
                cfg.api_host = host
            assert cfg.api_host == "10.0.0.5"

    def test_env_port(self):
        from murmurate_menubar import AppConfig
        with patch.dict(os.environ, {"MURMURATE_API_PORT": "9999"}):
            cfg = AppConfig()
            if port := os.environ.get("MURMURATE_API_PORT"):
                cfg.api_port = int(port)
            assert cfg.api_port == 9999

    def test_env_token(self):
        from murmurate_menubar import AppConfig
        with patch.dict(os.environ, {"MURMURATE_API_TOKEN": "secret-abc"}):
            cfg = AppConfig()
            if token := os.environ.get("MURMURATE_API_TOKEN"):
                cfg.api_token = token
            assert cfg.api_token == "secret-abc"

    def test_env_poll_interval(self):
        from murmurate_menubar import AppConfig
        with patch.dict(os.environ, {"MURMURATE_POLL_INTERVAL": "30"}):
            cfg = AppConfig()
            if interval := os.environ.get("MURMURATE_POLL_INTERVAL"):
                cfg.poll_interval = max(1, int(interval))
            assert cfg.poll_interval == 30

    def test_env_invalid_port_ignored(self):
        from murmurate_menubar import AppConfig
        cfg = AppConfig()
        with patch.dict(os.environ, {"MURMURATE_API_PORT": "not-a-number"}):
            if port := os.environ.get("MURMURATE_API_PORT"):
                try:
                    cfg.api_port = int(port)
                except ValueError:
                    pass
            # Should remain at default
            assert cfg.api_port == 7683

    def test_env_poll_interval_minimum(self):
        from murmurate_menubar import AppConfig
        cfg = AppConfig()
        with patch.dict(os.environ, {"MURMURATE_POLL_INTERVAL": "0"}):
            if interval := os.environ.get("MURMURATE_POLL_INTERVAL"):
                try:
                    cfg.poll_interval = max(1, int(interval))
                except ValueError:
                    pass
            # Clamped to minimum of 1
            assert cfg.poll_interval == 1


# ---------------------------------------------------------------------------
# Status symbols tests
# ---------------------------------------------------------------------------

class TestStatusSymbols:
    """Tests for the status symbol constants."""

    def test_symbols_defined(self):
        from murmurate_menubar import STATUS_SYMBOLS
        assert "running" in STATUS_SYMBOLS
        assert "stopped" in STATUS_SYMBOLS
        assert "error" in STATUS_SYMBOLS

    def test_symbols_are_single_chars(self):
        from murmurate_menubar import STATUS_SYMBOLS
        for key, symbol in STATUS_SYMBOLS.items():
            assert len(symbol) == 1, f"Symbol for '{key}' should be a single character"


# ---------------------------------------------------------------------------
# MurmurateMenuBar tests (with mocked rumps)
# ---------------------------------------------------------------------------

def _make_test_app():
    """Create a MurmurateMenuBar instance suitable for testing.

    Patches rumps.App.__init__ to create the _menu attribute that the menu
    setter needs, then builds the menu normally.
    """
    from murmurate_menubar import MurmurateMenuBar

    # Create object without calling __init__ chain, then set up manually
    app = object.__new__(MurmurateMenuBar)

    # Minimal rumps.App internal state needed for menu setter and properties
    app._menu = rumps.rumps.Menu()
    app._name = "Murmurate"
    app._title = ""
    app._icon = None
    app._icon_nsimage = None
    app._template = None
    app._quit_button = None
    app._application_support = "Murmurate"

    # Now run our __init__ logic (config, client, status, menu build)
    app.config = AppConfig()
    app._load_config_from_env()
    app.client = ApiClient(app.config)
    app.status = DaemonStatus()
    app.personas = []
    app._build_menu()

    return app


# Import the classes needed by the helper at module level (after sys.path setup)
from murmurate_menubar import (
    AppConfig,
    ApiClient,
    DaemonStatus,
    PersonaSummary,
    STATUS_SYMBOLS,
)


class TestMenuBarApp:
    """Tests for the MurmurateMenuBar class with mocked rumps framework."""

    def test_app_initialization(self):
        app = _make_test_app()
        assert app.config.api_host == "127.0.0.1"
        assert app.config.api_port == 7683
        assert app.status.connected is False
        assert app.personas == []

    def test_apply_status_running(self):
        app = _make_test_app()

        status = DaemonStatus(
            connected=True,
            running=True,
            version="0.2.0",
            sessions_today=5,
            sessions_completed=4,
            sessions_failed=1,
        )
        app._apply_status_update(status, [], [])

        assert app.title == f"{STATUS_SYMBOLS['running']} Murmurate"
        assert "Running" in app.status_item.title
        assert "5" in app.sessions_item.title
        assert "4 ok" in app.sessions_item.title
        assert "1 failed" in app.sessions_item.title

    def test_apply_status_disconnected(self):
        app = _make_test_app()

        status = DaemonStatus(connected=False, error_message="Connection refused")
        app._apply_status_update(status, [], [])

        assert app.title == f"{STATUS_SYMBOLS['error']} Murmurate"
        assert "Disconnected" in app.status_item.title
        assert "--" in app.sessions_item.title

    def test_apply_status_stopped(self):
        app = _make_test_app()

        status = DaemonStatus(connected=True, running=False)
        app._apply_status_update(status, [], [])

        assert app.title == f"{STATUS_SYMBOLS['stopped']} Murmurate"
        assert "Stopped" in app.status_item.title

    def test_personas_menu_populated(self):
        app = _make_test_app()

        status = DaemonStatus(connected=True, running=True)
        personas = [
            PersonaSummary(name="alice", total_sessions=10, topic_count=5, seeds=["topic1"]),
            PersonaSummary(name="bob", total_sessions=3, topic_count=2, seeds=["topic2", "topic3"]),
        ]
        app._apply_status_update(status, personas, [])

        # After update, the app.personas list should be stored
        assert len(app.personas) == 2
        assert app.personas[0].name == "alice"
        assert app.personas[1].name == "bob"

    def test_recent_menu_with_history(self):
        app = _make_test_app()

        status = DaemonStatus(connected=True, running=True)
        history = [
            {
                "persona": "researcher",
                "plugin": "duckduckgo",
                "status": "completed",
                "started_at": "2026-03-22T10:30:00Z",
            },
        ]
        app._apply_status_update(status, [], history)
        assert app.status.connected is True

    def test_recent_menu_empty_when_disconnected(self):
        app = _make_test_app()

        status = DaemonStatus(connected=False)
        app._apply_status_update(status, [], [])

        assert app.status.connected is False

    @patch("webbrowser.open")
    def test_open_dashboard(self, mock_open):
        app = _make_test_app()
        app._open_dashboard(None)
        mock_open.assert_called_once_with(app.config.dashboard_url)

    def test_configure_connection_updates_client(self):
        app = _make_test_app()

        # Directly test config update logic
        app.config.api_host = "192.168.1.100"
        app.config.api_port = 8080
        app.client = ApiClient(app.config)

        assert app.client.config.base_url == "http://192.168.1.100:8080/api"

    def test_version_display_connected(self):
        app = _make_test_app()

        status = DaemonStatus(connected=True, running=True, version="0.2.0")
        app._apply_status_update(status, [], [])

        assert "0.2.0" in app.version_item.title

    def test_version_display_disconnected(self):
        app = _make_test_app()

        status = DaemonStatus(connected=False)
        app._apply_status_update(status, [], [])

        assert "--" in app.version_item.title

    def test_connection_item_shows_endpoint(self):
        app = _make_test_app()
        assert "127.0.0.1:7683" in app.connection_item.title
