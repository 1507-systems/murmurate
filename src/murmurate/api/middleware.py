"""
middleware.py — CORS and authentication middleware for the API server.

CORS is permissive by default because the control UI is typically served from
a different origin (localhost:5173 during development, or a different port in
production). The auth middleware checks for a bearer token on non-GET requests
when an API token is configured.
"""

from __future__ import annotations

from aiohttp import web


@web.middleware
async def cors_middleware(request: web.Request, handler) -> web.Response:
    """Add CORS headers to all responses.

    Handles preflight OPTIONS requests automatically. Allows any origin
    because the API is intended for local or LAN use where origin restrictions
    provide no meaningful security — the bearer token is the auth boundary.
    """
    if request.method == "OPTIONS":
        return web.Response(
            status=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
                "Access-Control-Max-Age": "86400",
            },
        )

    response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@web.middleware
async def auth_middleware(request: web.Request, handler) -> web.Response:
    """Enforce bearer token authentication when an API token is configured.

    When no token is set in the config, all requests pass through — the server
    should be bound to 127.0.0.1 only in that case (enforced by the server
    startup logic, not here).

    API paths require auth; static file paths (no /api/ prefix) do not, so
    the web UI can always load even if the token is misconfigured.
    """
    state = request.app.get("state")
    if state is None:
        return await handler(request)

    token = getattr(state, "api_token", None)

    # No token configured — skip auth entirely
    if not token:
        return await handler(request)

    # Only require auth on API endpoints
    if not request.path.startswith("/api/"):
        return await handler(request)

    # Check the Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header == f"Bearer {token}":
        return await handler(request)

    return web.Response(
        text='{"error": "Unauthorized"}',
        status=401,
        content_type="application/json",
    )
