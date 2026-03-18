"""
server.py — aiohttp-based REST API server for the Murmurate Control UI.

The API server is designed to be embedded in the daemon process, sharing the
same event loop and state objects (config, database, registry, personas). This
avoids IPC entirely — the API reads and writes the same in-memory objects that
the scheduler uses.

The server serves:
  - REST API endpoints under /api/
  - Static files for the web UI from a bundled directory

Authentication uses a bearer token stored in the config. When the token is
not set, the API only binds to 127.0.0.1 (local access only). When a token
is set, it can optionally bind to 0.0.0.0 for remote access.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aiohttp import web

from murmurate.api.middleware import cors_middleware, auth_middleware

logger = logging.getLogger(__name__)


def create_app(state: "ApiState") -> web.Application:
    """Build and return the aiohttp Application with all routes registered.

    The ApiState object is stored on the app dict so handlers can access shared
    daemon state without globals. Middleware handles CORS and optional auth.
    """
    app = web.Application(middlewares=[cors_middleware, auth_middleware])
    app["state"] = state

    # API routes
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/daemon/stop", handle_daemon_stop)
    app.router.add_get("/api/personas", handle_personas_list)
    app.router.add_get("/api/personas/{name}", handle_persona_detail)
    app.router.add_post("/api/personas", handle_persona_create)
    app.router.add_put("/api/personas/{name}", handle_persona_update)
    app.router.add_delete("/api/personas/{name}", handle_persona_delete)
    app.router.add_get("/api/history", handle_history)
    app.router.add_get("/api/stats", handle_stats)
    app.router.add_get("/api/plugins", handle_plugins_list)
    app.router.add_get("/api/plugins/{name}", handle_plugin_detail)
    app.router.add_post("/api/plugins/{name}/enable", handle_plugin_enable)
    app.router.add_post("/api/plugins/{name}/disable", handle_plugin_disable)
    app.router.add_get("/api/config", handle_config_get)
    app.router.add_put("/api/config", handle_config_update)

    # Serve static files for the web UI (built React app)
    static_dir = Path(__file__).parent.parent.parent.parent / "control-ui" / "dist"
    if static_dir.is_dir():
        # Serve index.html for SPA routing (any non-API path)
        app.router.add_get("/{path:.*}", _make_spa_handler(static_dir))
        app.router.add_static("/assets", static_dir / "assets", show_index=False)

    return app


def _make_spa_handler(static_dir: Path):
    """Return a handler that serves index.html for SPA client-side routing."""
    # Resolve once at startup so all comparisons use the same canonical form
    resolved_root = static_dir.resolve()

    async def handle_spa(request: web.Request) -> web.Response:
        # Try to serve the exact file first (for assets like favicon, etc.)
        file_path = (static_dir / request.match_info.get("path", "")).resolve()
        # Guard against path traversal — the resolved path must stay inside
        # the static directory.  Without this check a request containing ../
        # sequences could read arbitrary files on disk.
        if (
            file_path.is_file()
            and file_path.suffix
            and str(file_path).startswith(str(resolved_root))
        ):
            return web.FileResponse(file_path)
        # Fall back to index.html for client-side routing
        index = static_dir / "index.html"
        if index.is_file():
            return web.FileResponse(index)
        return web.Response(text="Control UI not built. Run: cd control-ui && npm run build", status=404)
    return handle_spa


class ApiState:
    """Container for shared daemon state accessed by API handlers.

    This is the bridge between the daemon's runtime objects and the API. The
    daemon constructs this with references to its own state, and the API reads
    and writes through it.
    """

    def __init__(
        self,
        config,
        config_dir: Path,
        db=None,
        registry=None,
        scheduler=None,
        api_token: str | None = None,
    ):
        self.config = config
        self.config_dir = config_dir
        self.db = db
        self.registry = registry
        self.scheduler = scheduler
        self.api_token = api_token


def _json_response(data: Any, status: int = 200) -> web.Response:
    """Convenience wrapper for JSON responses with proper content type."""
    return web.Response(
        text=json.dumps(data, default=str),
        status=status,
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Handlers: Daemon status and control
# ---------------------------------------------------------------------------

async def handle_status(request: web.Request) -> web.Response:
    """GET /api/status — Return daemon running state and summary statistics."""
    state: ApiState = request.app["state"]

    result = {
        "running": state.scheduler is not None,
        "config_dir": str(state.config_dir),
        "version": "0.2.0",
    }

    # If we have a database, include recent session counts
    if state.db:
        try:
            sessions = await state.db.get_session_history(limit=10000)
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            today_sessions = [s for s in sessions if s.get("started_at", "") >= today_start]
            result["sessions_today"] = len(today_sessions)
            result["sessions_completed_today"] = sum(
                1 for s in today_sessions if s.get("status") == "completed"
            )
            result["sessions_failed_today"] = sum(
                1 for s in today_sessions if s.get("status") == "failed"
            )
        except Exception as exc:
            logger.warning("Failed to fetch session stats for status: %s", exc)

    return _json_response(result)


async def handle_daemon_stop(request: web.Request) -> web.Response:
    """POST /api/daemon/stop — Trigger graceful daemon shutdown."""
    state: ApiState = request.app["state"]
    if state.scheduler is not None and hasattr(state.scheduler, "stop"):
        state.scheduler.stop()
        return _json_response({"message": "Shutdown signal sent"})
    return _json_response({"error": "Scheduler not available"}, status=503)


# ---------------------------------------------------------------------------
# Handlers: Personas
# ---------------------------------------------------------------------------

async def handle_personas_list(request: web.Request) -> web.Response:
    """GET /api/personas — List all personas with summary info."""
    state: ApiState = request.app["state"]
    from murmurate.persona.storage import load_all_personas

    persona_dir = state.config_dir / "personas"
    personas = load_all_personas(persona_dir)

    result = []
    for p in personas:
        result.append({
            "name": p.name,
            "seeds": p.seeds,
            "total_sessions": p.total_sessions,
            "expertise_level": p.expertise_level,
            "created_at": p.created_at,
            "topic_count": _count_nodes(p.topic_tree),
        })

    return _json_response(result)


async def handle_persona_detail(request: web.Request) -> web.Response:
    """GET /api/personas/{name} — Full persona detail including topic tree."""
    state: ApiState = request.app["state"]
    name = request.match_info["name"]
    if err := _validate_persona_name(name):
        return err

    from murmurate.persona.storage import load_persona
    persona_file = state.config_dir / "personas" / f"{name}.json"

    if not persona_file.exists():
        return _json_response({"error": f"Persona '{name}' not found"}, status=404)

    try:
        persona = load_persona(persona_file)
        return _json_response(asdict(persona))
    except Exception as exc:
        return _json_response({"error": str(exc)}, status=500)


async def handle_persona_create(request: web.Request) -> web.Response:
    """POST /api/personas — Create a new persona.

    Expects JSON body: {"name": "...", "seeds": ["...", "..."]}
    Seeds are optional; random seeds are generated if not provided.
    """
    state: ApiState = request.app["state"]

    try:
        body = await request.json()
    except Exception:
        return _json_response({"error": "Invalid JSON body"}, status=400)

    name = body.get("name", "").strip()
    if not name:
        return _json_response({"error": "Name is required"}, status=400)

    # Sanitise: persona names become filenames, so reject path separators
    # and other dangerous characters to prevent directory traversal.
    if not _SAFE_NAME_RE.match(name):
        return _json_response(
            {"error": "Name must contain only letters, numbers, hyphens, and underscores"},
            status=400,
        )

    # Check for name collisions
    persona_dir = state.config_dir / "personas"
    persona_dir.mkdir(parents=True, exist_ok=True)

    if (persona_dir / f"{name}.json").exists():
        return _json_response({"error": f"Persona '{name}' already exists"}, status=409)

    from datetime import datetime as dt, timezone
    from murmurate.models import PersonaState, TopicNode
    from murmurate.persona.fingerprint import generate_fingerprint
    from murmurate.persona.storage import save_persona
    from murmurate.persona.topics import get_random_seeds

    seeds = body.get("seeds", [])
    if not seeds:
        seeds = get_random_seeds(3)

    fp = generate_fingerprint()
    now = dt.now(timezone.utc).isoformat()

    tree = [
        TopicNode(topic=s, depth=0, children=[], query_count=0, last_used=None)
        for s in seeds
    ]

    persona = PersonaState(
        name=name,
        version=1,
        seeds=seeds,
        topic_tree=tree,
        fingerprint=fp,
        created_at=now,
    )

    save_persona(persona, persona_dir)
    return _json_response({"message": f"Persona '{name}' created", "name": name}, status=201)


async def handle_persona_update(request: web.Request) -> web.Response:
    """PUT /api/personas/{name} — Update persona seeds (limited edit surface)."""
    state: ApiState = request.app["state"]
    name = request.match_info["name"]
    if err := _validate_persona_name(name):
        return err

    persona_file = state.config_dir / "personas" / f"{name}.json"
    if not persona_file.exists():
        return _json_response({"error": f"Persona '{name}' not found"}, status=404)

    try:
        body = await request.json()
    except Exception:
        return _json_response({"error": "Invalid JSON body"}, status=400)

    from murmurate.persona.storage import load_persona, save_persona
    from murmurate.models import TopicNode

    persona = load_persona(persona_file)

    # Allow updating seeds — add new seed topics as root nodes
    new_seeds = body.get("seeds")
    if new_seeds is not None:
        existing_topics = {node.topic for node in persona.topic_tree}
        for seed in new_seeds:
            if seed not in existing_topics:
                persona.seeds.append(seed)
                persona.topic_tree.append(
                    TopicNode(topic=seed, depth=0, children=[], query_count=0, last_used=None)
                )

    persona.version += 1
    persona_dir = state.config_dir / "personas"
    save_persona(persona, persona_dir)

    return _json_response({"message": f"Persona '{name}' updated"})


async def handle_persona_delete(request: web.Request) -> web.Response:
    """DELETE /api/personas/{name} — Delete a persona file."""
    state: ApiState = request.app["state"]
    name = request.match_info["name"]
    if err := _validate_persona_name(name):
        return err

    persona_file = state.config_dir / "personas" / f"{name}.json"
    if not persona_file.exists():
        return _json_response({"error": f"Persona '{name}' not found"}, status=404)

    # Move to trash instead of deleting (per project conventions)
    import shutil
    trash = Path.home() / ".Trash"
    shutil.move(str(persona_file), str(trash / persona_file.name))

    return _json_response({"message": f"Persona '{name}' deleted"})


# ---------------------------------------------------------------------------
# Handlers: History and stats
# ---------------------------------------------------------------------------

async def handle_history(request: web.Request) -> web.Response:
    """GET /api/history?limit=50 — Return recent session history."""
    state: ApiState = request.app["state"]
    if not state.db:
        return _json_response({"error": "Database not available"}, status=503)

    try:
        limit = max(1, min(int(request.query.get("limit", "50")), 10000))
    except (ValueError, TypeError):
        limit = 50
    sessions = await state.db.get_session_history(limit=limit)
    return _json_response(sessions)


async def handle_stats(request: web.Request) -> web.Response:
    """GET /api/stats?days=7 — Return activity statistics."""
    state: ApiState = request.app["state"]
    if not state.db:
        return _json_response({"error": "Database not available"}, status=503)

    try:
        days = max(1, min(int(request.query.get("days", "7")), 365))
    except (ValueError, TypeError):
        days = 7
    sessions = await state.db.get_session_history(limit=10000)

    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [s for s in sessions if s.get("started_at", "") >= cutoff]

    total = len(recent)
    completed = sum(1 for s in recent if s.get("status") == "completed")
    failed = sum(1 for s in recent if s.get("status") == "failed")

    # Plugin distribution
    plugins = {}
    for s in recent:
        p = s.get("plugin_name", "unknown")
        plugins[p] = plugins.get(p, 0) + 1

    # Transport distribution
    transports = {}
    for s in recent:
        t = s.get("transport_type", "unknown")
        transports[t] = transports.get(t, 0) + 1

    # Daily breakdown
    daily = {}
    for s in recent:
        day = s.get("started_at", "")[:10]
        if day:
            daily[day] = daily.get(day, 0) + 1

    return _json_response({
        "days": days,
        "total": total,
        "completed": completed,
        "failed": failed,
        "plugins": plugins,
        "transports": transports,
        "daily": daily,
    })


# ---------------------------------------------------------------------------
# Handlers: Plugins
# ---------------------------------------------------------------------------

async def handle_plugins_list(request: web.Request) -> web.Response:
    """GET /api/plugins — List all available plugins with status."""
    state: ApiState = request.app["state"]

    # Load a fresh registry if one isn't available from the daemon
    from murmurate.plugins.registry import PluginRegistry
    registry = state.registry or PluginRegistry()
    if not state.registry:
        registry.load_bundled()

    result = []
    for name, plugin in registry.all_plugins.items():
        info = registry.get_plugin_info(name)
        if info:
            result.append(info)

    return _json_response(result)


async def handle_plugin_detail(request: web.Request) -> web.Response:
    """GET /api/plugins/{name} — Get detailed plugin information."""
    state: ApiState = request.app["state"]
    name = request.match_info["name"]

    from murmurate.plugins.registry import PluginRegistry
    registry = state.registry or PluginRegistry()
    if not state.registry:
        registry.load_bundled()

    info = registry.get_plugin_info(name)
    if not info:
        return _json_response({"error": f"Plugin '{name}' not found"}, status=404)

    return _json_response(info)


async def handle_plugin_enable(request: web.Request) -> web.Response:
    """POST /api/plugins/{name}/enable — Enable a plugin."""
    state: ApiState = request.app["state"]
    name = request.match_info["name"]

    if not state.registry:
        return _json_response({"error": "Registry not available"}, status=503)

    if state.registry.get_plugin(name) is None:
        return _json_response({"error": f"Plugin '{name}' not found"}, status=404)

    state.registry.enable(name)
    return _json_response({"message": f"Plugin '{name}' enabled"})


async def handle_plugin_disable(request: web.Request) -> web.Response:
    """POST /api/plugins/{name}/disable — Disable a plugin."""
    state: ApiState = request.app["state"]
    name = request.match_info["name"]

    if not state.registry:
        return _json_response({"error": "Registry not available"}, status=503)

    if state.registry.get_plugin(name) is None:
        return _json_response({"error": f"Plugin '{name}' not found"}, status=404)

    state.registry.disable(name)
    return _json_response({"message": f"Plugin '{name}' disabled"})


# ---------------------------------------------------------------------------
# Handlers: Configuration
# ---------------------------------------------------------------------------

async def handle_config_get(request: web.Request) -> web.Response:
    """GET /api/config — Return current configuration as JSON."""
    state: ApiState = request.app["state"]
    return _json_response(asdict(state.config))


async def handle_config_update(request: web.Request) -> web.Response:
    """PUT /api/config — Update configuration and write to disk.

    Accepts a partial config object — only provided fields are updated.
    Triggers a config reload in the daemon (equivalent to SIGHUP).
    """
    state: ApiState = request.app["state"]

    try:
        body = await request.json()
    except Exception:
        return _json_response({"error": "Invalid JSON body"}, status=400)

    import tomli_w

    config_file = state.config_dir / "config.toml"

    # Build the TOML structure from the update
    # We write back the full config to keep the file complete
    current = asdict(state.config)
    _deep_update(current, body)

    # Write to disk
    with open(config_file, "wb") as f:
        tomli_w.dump(current, f)

    # Reload config in memory
    from murmurate.config import load_config
    state.config = load_config(state.config_dir)

    return _json_response({"message": "Configuration updated"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_persona_name(name: str) -> web.Response | None:
    """Return an error response if the name is unsafe, or None if it's valid.

    Persona names are used to construct file paths, so we reject anything
    containing path separators or special characters to prevent traversal.
    """
    if not name or not _SAFE_NAME_RE.match(name):
        return _json_response(
            {"error": "Invalid persona name — use only letters, numbers, hyphens, underscores"},
            status=400,
        )
    return None


def _count_nodes(nodes: list) -> int:
    """Count total nodes in a topic tree (recursive)."""
    count = 0
    for node in nodes:
        count += 1
        if hasattr(node, "children"):
            count += _count_nodes(node.children)
        elif isinstance(node, dict):
            count += _count_nodes(node.get("children", []))
    return count


def _deep_update(base: dict, updates: dict) -> None:
    """Recursively merge updates into base dict (in-place)."""
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
