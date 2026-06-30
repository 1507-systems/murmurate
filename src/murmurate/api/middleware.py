"""
middleware.py — Host-allowlist, CORS, and authentication middleware.

The middleware chain runs in order: ``host_allowlist_middleware`` first, then
``cors_middleware``, then ``auth_middleware``.

Host allowlist (DNS-rebinding defense): the Control UI binds to loopback with
no token in the default config, and the auth middleware then allows every
request. That is only safe against a *network* attacker — it does nothing
against DNS rebinding, where a malicious web page the operator visits resolves
its own hostname to 127.0.0.1 and drives the local daemon from the browser.
The browser still sends the attacker's hostname in the Host header, so we
reject any request whose Host is not an allowed loopback name (or the configured
bind host). This runs before any handler and fails closed.

CORS is permissive by default because the control UI is typically served from
a different origin (localhost:5173 during development, or a different port in
production). It is NOT a security boundary — the host allowlist and the bearer
token are. The auth middleware checks for a bearer token on API requests when
an API token is configured.
"""

from __future__ import annotations

from aiohttp import web


# Host names (sans port) that always identify the local machine. A request
# whose Host header resolves to one of these cannot have been smuggled in via
# DNS rebinding, because the browser would have to send the *attacker's*
# hostname. The configured bind host is added to this set at request time.
_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _host_without_port(raw_host: str) -> str:
    """Return the host portion of a Host header value, lower-cased, no port.

    Handles IPv6 literals in brackets (``[::1]:7683`` → ``::1``) and ordinary
    ``host:port`` forms (``localhost:7683`` → ``localhost``). A bare IPv6
    literal with no port (which still contains colons) is returned unchanged.
    """
    host = raw_host.strip().lower()
    if host.startswith("["):
        # Bracketed IPv6 literal, optionally followed by :port
        end = host.find("]")
        if end != -1:
            return host[1:end]
        return host
    # Only treat a trailing :port as a port when there is exactly one colon;
    # multiple colons indicate a bare IPv6 literal (e.g. "::1").
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host


@web.middleware
async def host_allowlist_middleware(request: web.Request, handler) -> web.Response:
    """Reject requests whose Host header is not an allowed loopback/bind host.

    This neutralizes DNS-rebinding attacks regardless of whether an API token
    is configured: a rebinding page can point its hostname at 127.0.0.1, but it
    cannot forge the Host header the browser sends, so requests for the
    attacker's hostname are refused with 403.

    The allowlist is the loopback names plus the host the server was told to
    bind to (read from ``state.bind_host`` when present). A missing/empty Host
    header is rejected — fail closed.
    """
    allowed = set(_ALLOWED_HOSTS)
    state = request.app.get("state")
    bind_host = getattr(state, "bind_host", None) if state is not None else None
    if bind_host:
        normalized = bind_host.strip().lower()
        # The wildcard binds do not name a reachable host; loopback names
        # already cover local access, so do not widen the allowlist for them.
        if normalized not in ("", "0.0.0.0", "::"):
            allowed.add(normalized)

    host = _host_without_port(request.headers.get("Host", ""))
    if host not in allowed:
        return web.Response(
            text='{"error": "Forbidden: Host header not allowed"}',
            status=403,
            content_type="application/json",
        )

    return await handler(request)


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

    When no token is set, all API requests pass through. This is only safe
    because two other controls fail closed first: the CLI refuses to bind a
    non-loopback address without a token (cli.py _require_token_for_nonloopback),
    and ``host_allowlist_middleware`` rejects any request whose Host header is
    not a loopback/bind host (blocking DNS rebinding). Do not rely on this
    middleware alone for the no-token case.

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
