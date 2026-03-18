"""
Tests for the Murmurate REST API server.

Uses aiohttp's test utilities to test each endpoint without starting a real
server. The ApiState is populated with mock/test objects so we can verify
handlers in isolation.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web

from murmurate.api.server import ApiState, create_app, _count_nodes, _deep_update
from murmurate.config import MurmurateConfig


@pytest.fixture
def config():
    """Return a default MurmurateConfig for testing."""
    return MurmurateConfig()


@pytest.fixture
def config_dir(tmp_path):
    """Create a temp config directory with a personas subdirectory."""
    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()
    return tmp_path


@pytest.fixture
def mock_db():
    """Return a mock StateDB with async methods."""
    db = MagicMock()
    db.get_session_history = AsyncMock(return_value=[])
    db.initialize = AsyncMock()
    db.close = AsyncMock()
    return db


@pytest.fixture
def mock_registry():
    """Return a mock PluginRegistry with test data."""
    registry = MagicMock()
    registry.all_plugins = {}
    registry.get_plugin_info = MagicMock(return_value=None)
    registry.get_plugin = MagicMock(return_value=None)
    registry.enable = MagicMock()
    registry.disable = MagicMock()
    return registry


@pytest.fixture
def api_state(config, config_dir, mock_db, mock_registry):
    """Return an ApiState wired up with test fixtures."""
    return ApiState(
        config=config,
        config_dir=config_dir,
        db=mock_db,
        registry=mock_registry,
        scheduler=None,
        api_token=None,
    )


@pytest.fixture
def app(api_state):
    """Create the aiohttp app for testing."""
    return create_app(api_state)


@pytest.fixture
async def client(aiohttp_client, app):
    """Create an aiohttp test client."""
    return await aiohttp_client(app)


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------

async def test_status_returns_basic_info(client):
    """GET /api/status should return daemon status info."""
    resp = await client.get("/api/status")
    assert resp.status == 200
    data = await resp.json()
    assert "running" in data
    assert "version" in data
    assert data["running"] is False  # No scheduler set


async def test_status_includes_session_counts(client, mock_db):
    """GET /api/status should include today's session count when db is available."""
    mock_db.get_session_history.return_value = [
        {"started_at": "2099-01-01T10:00:00+00:00", "status": "completed"},
        {"started_at": "2099-01-01T12:00:00+00:00", "status": "failed"},
    ]
    resp = await client.get("/api/status")
    data = await resp.json()
    # Session counts depend on "today" — just verify the keys exist
    assert "sessions_today" in data


# ---------------------------------------------------------------------------
# Daemon stop
# ---------------------------------------------------------------------------

async def test_stop_without_scheduler(client):
    """POST /api/daemon/stop should return 503 when no scheduler is running."""
    resp = await client.post("/api/daemon/stop")
    assert resp.status == 503


async def test_stop_with_scheduler(client, api_state):
    """POST /api/daemon/stop should call scheduler.stop() when available."""
    scheduler = MagicMock()
    api_state.scheduler = scheduler

    resp = await client.post("/api/daemon/stop")
    assert resp.status == 200
    scheduler.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

async def test_personas_list_empty(client):
    """GET /api/personas should return empty list when no personas exist."""
    resp = await client.get("/api/personas")
    assert resp.status == 200
    data = await resp.json()
    assert data == []


async def test_persona_create(client, config_dir):
    """POST /api/personas should create a new persona file."""
    resp = await client.post(
        "/api/personas",
        json={"name": "test-persona", "seeds": ["cooking", "baking"]},
    )
    assert resp.status == 201
    data = await resp.json()
    assert data["name"] == "test-persona"

    # Verify the file was created
    persona_file = config_dir / "personas" / "test-persona.json"
    assert persona_file.exists()


async def test_persona_create_duplicate(client, config_dir):
    """POST /api/personas should return 409 for duplicate names."""
    # Create the first one
    await client.post(
        "/api/personas",
        json={"name": "dupe", "seeds": ["test"]},
    )
    # Try to create again
    resp = await client.post(
        "/api/personas",
        json={"name": "dupe", "seeds": ["test"]},
    )
    assert resp.status == 409


async def test_persona_create_no_name(client):
    """POST /api/personas should return 400 when name is missing."""
    resp = await client.post("/api/personas", json={"seeds": ["test"]})
    assert resp.status == 400


async def test_persona_detail_not_found(client):
    """GET /api/personas/{name} should return 404 for missing persona."""
    resp = await client.get("/api/personas/nonexistent")
    assert resp.status == 404


async def test_persona_detail(client, config_dir):
    """GET /api/personas/{name} should return full persona data."""
    # Create a persona first
    await client.post(
        "/api/personas",
        json={"name": "detail-test", "seeds": ["gardening"]},
    )
    resp = await client.get("/api/personas/detail-test")
    assert resp.status == 200
    data = await resp.json()
    assert data["name"] == "detail-test"
    assert "fingerprint" in data
    assert "topic_tree" in data


async def test_persona_delete(client, config_dir):
    """DELETE /api/personas/{name} should move persona file to trash."""
    # Create a persona
    await client.post(
        "/api/personas",
        json={"name": "to-delete", "seeds": ["temp"]},
    )
    persona_file = config_dir / "personas" / "to-delete.json"
    assert persona_file.exists()

    resp = await client.delete("/api/personas/to-delete")
    assert resp.status == 200
    assert not persona_file.exists()


async def test_persona_delete_not_found(client):
    """DELETE /api/personas/{name} should return 404 for missing persona."""
    resp = await client.delete("/api/personas/nonexistent")
    assert resp.status == 404


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

async def test_history_empty(client, mock_db):
    """GET /api/history should return empty list when no sessions."""
    resp = await client.get("/api/history")
    assert resp.status == 200
    data = await resp.json()
    assert data == []


async def test_history_with_data(client, mock_db):
    """GET /api/history should return sessions from the database."""
    mock_db.get_session_history.return_value = [
        {"id": "abc", "persona_name": "test", "plugin_name": "google",
         "status": "completed", "started_at": "2026-01-01T00:00:00"},
    ]
    resp = await client.get("/api/history?limit=10")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "abc"
    mock_db.get_session_history.assert_called_with(limit=10)


async def test_history_no_db(client, api_state):
    """GET /api/history should return 503 when database is unavailable."""
    api_state.db = None
    resp = await client.get("/api/history")
    assert resp.status == 503


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

async def test_stats_empty(client, mock_db):
    """GET /api/stats should return zero counts when no sessions."""
    resp = await client.get("/api/stats")
    assert resp.status == 200
    data = await resp.json()
    assert data["total"] == 0
    assert data["completed"] == 0
    assert data["plugins"] == {}


async def test_stats_with_data(client, mock_db):
    """GET /api/stats should compute correct statistics."""
    mock_db.get_session_history.return_value = [
        {"started_at": "2099-01-01T10:00:00", "status": "completed",
         "plugin_name": "google", "transport_type": "http"},
        {"started_at": "2099-01-01T12:00:00", "status": "completed",
         "plugin_name": "youtube", "transport_type": "browser"},
        {"started_at": "2099-01-01T14:00:00", "status": "failed",
         "plugin_name": "google", "transport_type": "http"},
    ]
    resp = await client.get("/api/stats?days=3650")
    assert resp.status == 200
    data = await resp.json()
    assert data["total"] == 3
    assert data["completed"] == 2
    assert data["failed"] == 1
    assert data["plugins"]["google"] == 2
    assert data["plugins"]["youtube"] == 1


# ---------------------------------------------------------------------------
# Plugins
# ---------------------------------------------------------------------------

async def test_plugins_list(client, mock_registry):
    """GET /api/plugins should return all registered plugins."""
    mock_registry.all_plugins = {"google": MagicMock(), "youtube": MagicMock()}
    mock_registry.get_plugin_info.side_effect = [
        {"name": "google", "enabled": True, "rate_limit_rpm": 8,
         "preferred_transport": "either", "consecutive_failures": 0, "domains": ["google.com"]},
        {"name": "youtube", "enabled": True, "rate_limit_rpm": 10,
         "preferred_transport": "browser", "consecutive_failures": 0, "domains": ["youtube.com"]},
    ]
    resp = await client.get("/api/plugins")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 2


async def test_plugin_enable(client, mock_registry):
    """POST /api/plugins/{name}/enable should call registry.enable()."""
    mock_registry.get_plugin.return_value = MagicMock()
    resp = await client.post("/api/plugins/google/enable")
    assert resp.status == 200
    mock_registry.enable.assert_called_once_with("google")


async def test_plugin_disable(client, mock_registry):
    """POST /api/plugins/{name}/disable should call registry.disable()."""
    mock_registry.get_plugin.return_value = MagicMock()
    resp = await client.post("/api/plugins/google/disable")
    assert resp.status == 200
    mock_registry.disable.assert_called_once_with("google")


async def test_plugin_enable_not_found(client, mock_registry):
    """POST /api/plugins/{name}/enable should 404 for unknown plugins."""
    mock_registry.get_plugin.return_value = None
    resp = await client.post("/api/plugins/fake/enable")
    assert resp.status == 404


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

async def test_config_get(client):
    """GET /api/config should return the current config as JSON."""
    resp = await client.get("/api/config")
    assert resp.status == 200
    data = await resp.json()
    assert "config_version" in data
    assert "scheduler" in data
    assert "transport" in data


async def test_config_update(client, config_dir):
    """PUT /api/config should write changes and reload."""
    resp = await client.put(
        "/api/config",
        json={"scheduler": {"burst_probability": 0.25}},
    )
    assert resp.status == 200
    data = await resp.json()
    assert "updated" in data["message"].lower() or "saved" in data["message"].lower()

    # Verify config.toml was written
    config_file = config_dir / "config.toml"
    assert config_file.exists()


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

async def test_cors_preflight(client):
    """OPTIONS request should return CORS headers."""
    resp = await client.options("/api/status")
    assert resp.status == 204
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"


async def test_cors_headers_on_response(client):
    """Regular responses should include CORS headers."""
    resp = await client.get("/api/status")
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

async def test_auth_no_token_required(client):
    """Requests should pass when no API token is configured."""
    resp = await client.get("/api/status")
    assert resp.status == 200


async def test_auth_with_token(aiohttp_client, config, config_dir, mock_db, mock_registry):
    """Requests should require bearer token when one is configured."""
    state = ApiState(
        config=config,
        config_dir=config_dir,
        db=mock_db,
        registry=mock_registry,
        scheduler=None,
        api_token="test-secret-token",
    )
    app = create_app(state)
    client = await aiohttp_client(app)

    # Without token — should be rejected
    resp = await client.get("/api/status")
    assert resp.status == 401

    # With wrong token — should be rejected
    resp = await client.get("/api/status", headers={"Authorization": "Bearer wrong"})
    assert resp.status == 401

    # With correct token — should pass
    resp = await client.get(
        "/api/status",
        headers={"Authorization": "Bearer test-secret-token"},
    )
    assert resp.status == 200


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def test_count_nodes_empty():
    """_count_nodes should return 0 for empty list."""
    assert _count_nodes([]) == 0


def test_count_nodes_nested():
    """_count_nodes should count all nodes recursively."""
    from murmurate.models import TopicNode
    tree = [
        TopicNode(topic="a", depth=0, children=[
            TopicNode(topic="b", depth=1, children=[
                TopicNode(topic="c", depth=2),
            ]),
            TopicNode(topic="d", depth=1),
        ]),
    ]
    assert _count_nodes(tree) == 4


def test_deep_update():
    """_deep_update should merge nested dicts."""
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    _deep_update(base, {"a": {"b": 99}, "e": 4})
    assert base == {"a": {"b": 99, "c": 2}, "d": 3, "e": 4}
