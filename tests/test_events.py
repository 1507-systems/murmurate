"""
Tests for the SSE EventBus (api/events.py).

Verifies:
  - broadcast() delivers events to registered queues
  - broadcast() silently drops events when a queue is full
  - handle_sse() responds with text/event-stream content type
  - handle_sse() rejects connections beyond MAX_SSE_CONNECTIONS
  - connection_count reflects the subscriber count
  - ApiState always has an event_bus attribute
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from murmurate.api.events import EventBus, MAX_SSE_CONNECTIONS
from murmurate.api.server import ApiState, create_app
from murmurate.config import MurmurateConfig


# ---------------------------------------------------------------------------
# EventBus unit tests (no HTTP)
# ---------------------------------------------------------------------------

def test_event_bus_starts_empty():
    """A fresh EventBus has no subscribers and count is 0."""
    bus = EventBus()
    assert bus.connection_count == 0


def test_broadcast_with_no_subscribers_is_noop():
    """broadcast() with zero subscribers should not raise."""
    bus = EventBus()
    bus.broadcast("test_event", {"key": "value"})  # no error


def test_broadcast_delivers_to_queue():
    """broadcast() should put a serialised payload into each subscriber queue."""
    bus = EventBus()
    q = bus._add_queue()

    bus.broadcast("session_completed", {"session_id": "abc123"})

    assert not q.empty()
    payload = q.get_nowait()
    data = json.loads(payload)
    assert data["type"] == "session_completed"
    assert data["session_id"] == "abc123"
    assert "ts" in data


def test_broadcast_delivers_to_multiple_queues():
    """broadcast() should reach all registered queues."""
    bus = EventBus()
    q1 = bus._add_queue()
    q2 = bus._add_queue()
    q3 = bus._add_queue()

    bus.broadcast("ping", {})

    assert not q1.empty()
    assert not q2.empty()
    assert not q3.empty()


def test_broadcast_drops_event_on_full_queue():
    """broadcast() should silently drop events for a queue that is full."""
    bus = EventBus()
    q = bus._add_queue()

    # Fill the queue to capacity (maxsize=100)
    for _ in range(100):
        q.put_nowait("filler")

    # This should not raise — the event is dropped for the full queue
    bus.broadcast("overflow", {"x": 1})
    assert q.full()


def test_remove_queue_decrements_count():
    """_remove_queue should remove the queue from the subscriber set."""
    bus = EventBus()
    q = bus._add_queue()
    assert bus.connection_count == 1
    bus._remove_queue(q)
    assert bus.connection_count == 0


def test_remove_nonexistent_queue_is_noop():
    """_remove_queue on an unknown queue should not raise."""
    bus = EventBus()
    q: asyncio.Queue = asyncio.Queue()
    bus._remove_queue(q)  # should not raise


# ---------------------------------------------------------------------------
# SSE HTTP endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    return MurmurateConfig()


@pytest.fixture
def config_dir(tmp_path):
    (tmp_path / "personas").mkdir()
    return tmp_path


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_session_history = AsyncMock(return_value=[])
    db.initialize = AsyncMock()
    db.close = AsyncMock()
    return db


@pytest.fixture
def mock_registry():
    registry = MagicMock()
    registry.all_plugins = {}
    registry.get_plugin_info = MagicMock(return_value=None)
    registry.get_plugin = MagicMock(return_value=None)
    registry.enable = MagicMock()
    registry.disable = MagicMock()
    return registry


@pytest.fixture
def api_state(config, config_dir, mock_db, mock_registry):
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
    return create_app(api_state)


@pytest.fixture
async def client(aiohttp_client, app):
    return await aiohttp_client(app)


async def test_api_state_has_event_bus(api_state):
    """ApiState should always have an event_bus attribute."""
    assert hasattr(api_state, "event_bus")
    assert isinstance(api_state.event_bus, EventBus)


async def test_app_has_event_bus(app):
    """The aiohttp app dict should include the event_bus key."""
    assert "event_bus" in app
    assert isinstance(app["event_bus"], EventBus)


async def test_sse_endpoint_returns_event_stream_content_type(aiohttp_client, app):
    """GET /api/events should return Content-Type: text/event-stream."""
    # We need to open the connection and then close it quickly to avoid blocking.
    # Use a low-level approach: just check the response headers.
    client = await aiohttp_client(app)

    # Start a request but cancel it immediately after reading headers
    async with client.session.get(client.make_url("/api/events")) as resp:
        assert resp.status == 200
        assert "text/event-stream" in resp.headers.get("Content-Type", "")
        # Read the first chunk (the "connected" event) then stop
        chunk = await resp.content.read(256)
        assert b"data:" in chunk
        assert b"connected" in chunk


async def test_sse_endpoint_sends_connected_event(aiohttp_client, app):
    """GET /api/events should immediately send a 'connected' event."""
    client = await aiohttp_client(app)

    async with client.session.get(client.make_url("/api/events")) as resp:
        assert resp.status == 200
        raw = await resp.content.read(512)
        text = raw.decode()
        # Parse the first SSE data line
        for line in text.splitlines():
            if line.startswith("data:"):
                event = json.loads(line[5:].strip())
                assert event["type"] == "connected"
                break
        else:
            pytest.fail("No data: line found in SSE response")


async def test_sse_endpoint_rejects_over_limit(aiohttp_client, app):
    """GET /api/events should return 503 when MAX_SSE_CONNECTIONS is exceeded."""
    bus: EventBus = app["event_bus"]

    # Manually fill the subscriber set up to the limit
    fake_queues = []
    for _ in range(MAX_SSE_CONNECTIONS):
        q = bus._add_queue()
        fake_queues.append(q)

    try:
        client = await aiohttp_client(app)
        resp = await client.get("/api/events")
        assert resp.status == 503
        data = await resp.json()
        assert "error" in data
    finally:
        for q in fake_queues:
            bus._remove_queue(q)


async def test_status_includes_sse_connections(client, api_state):
    """GET /api/status should include the sse_connections count."""
    resp = await client.get("/api/status")
    assert resp.status == 200
    data = await resp.json()
    assert "sse_connections" in data
    assert isinstance(data["sse_connections"], int)


async def test_broadcast_from_state_reaches_queue(api_state):
    """Calling api_state.event_bus.broadcast() should reach subscriber queues."""
    bus = api_state.event_bus
    q = bus._add_queue()

    api_state.event_bus.broadcast("test_event", {"payload": 42})

    assert not q.empty()
    payload = q.get_nowait()
    data = json.loads(payload)
    assert data["payload"] == 42
    bus._remove_queue(q)
