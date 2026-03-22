"""
events.py — Server-Sent Events (SSE) broadcaster for real-time session updates.

The EventBus holds a set of active SSE connections. When the scheduler
completes or starts a session it calls broadcast(), which pushes a JSON
event to every connected client.

SSE was chosen over WebSocket because:
- Session updates are unidirectional (server → client only).
- SSE works over plain HTTP/1.1 with no handshake overhead.
- Built-in browser reconnect logic handles dropped connections.
- aiohttp supports streaming responses natively with no extra deps.

Event format (SSE spec):
    data: {"type": "session_started", ...}\n\n

Clients can filter by event type in the "type" field inside the JSON data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)

# Maximum number of concurrent SSE connections. Beyond this limit new
# connections receive a 503 so the server cannot be memory-exhausted by
# many idle browser tabs.
MAX_SSE_CONNECTIONS = 50


class EventBus:
    """Manages SSE subscriber queues and broadcasts events to all of them.

    The EventBus is created once and stored on the aiohttp Application dict
    so all request handlers can reach it via ``request.app["event_bus"]``.
    """

    def __init__(self) -> None:
        # Each subscriber gets its own asyncio.Queue so broadcast() puts
        # events without blocking and each handler drains independently.
        self._queues: set[asyncio.Queue] = set()

    @property
    def connection_count(self) -> int:
        """Return number of active SSE connections."""
        return len(self._queues)

    def _add_queue(self) -> asyncio.Queue:
        """Register a new subscriber queue and return it."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._queues.add(q)
        return q

    def _remove_queue(self, q: asyncio.Queue) -> None:
        """Unregister a subscriber queue when the connection closes."""
        self._queues.discard(q)

    def broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        """Push an event to all connected SSE clients (non-blocking).

        Called from the scheduler or any other daemon component when
        something noteworthy happens. Does not block the caller — events
        that cannot fit into a subscriber's queue are silently dropped for
        that subscriber (the client will catch up on the next poll or
        reconnect).
        """
        payload = json.dumps({"type": event_type, "ts": time.time(), **data})
        dead: list[asyncio.Queue] = []
        for q in self._queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop the event for this slow consumer rather than blocking.
                logger.debug("SSE queue full for one subscriber — event dropped")
            except Exception as exc:
                logger.warning("SSE broadcast error: %s", exc)
                dead.append(q)
        for q in dead:
            self._queues.discard(q)

    async def handle_sse(self, request: web.Request) -> web.StreamResponse:
        """GET /api/events — SSE stream handler.

        Keeps the HTTP connection open and streams events as they arrive.
        The client receives a heartbeat comment every 15 seconds to keep
        proxies and load balancers from timing out idle connections.
        """
        if len(self._queues) >= MAX_SSE_CONNECTIONS:
            return web.Response(
                text='{"error": "Too many SSE connections"}',
                status=503,
                content_type="application/json",
            )

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # Disable nginx buffering if proxied
            },
        )
        await response.prepare(request)

        # Send an initial "connected" event so the client knows the stream is live
        await _write_event(response, "connected", {"connections": len(self._queues) + 1})

        q = self._add_queue()
        try:
            while True:
                try:
                    # Wait up to 15 seconds, then send a heartbeat comment
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    await _write_event_raw(response, payload)
                except asyncio.TimeoutError:
                    # SSE comment (": ...") keeps the connection alive
                    await response.write(b": heartbeat\n\n")
                except (ConnectionResetError, asyncio.CancelledError):
                    break
        finally:
            self._remove_queue(q)

        return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _write_event(response: web.StreamResponse, event_type: str, data: dict) -> None:
    """Write a single SSE event with a named type field."""
    payload = json.dumps({"type": event_type, "ts": time.time(), **data})
    await _write_event_raw(response, payload)


async def _write_event_raw(response: web.StreamResponse, payload: str) -> None:
    """Write a pre-serialised SSE data line."""
    await response.write(f"data: {payload}\n\n".encode())
