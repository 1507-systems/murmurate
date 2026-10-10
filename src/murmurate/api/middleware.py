"""
middleware.py — Host-allowlist, Origin-check, and authentication middleware.

The middleware chain runs in order: ``host_allowlist_middleware`` first, then
``origin_middleware``, then ``auth_middleware``.

Host allowlist (DNS-rebinding defense): the Control UI binds to loopback by
default, and the auth middleware then allows every request whose token (or,
formerly, lack of one) matches. That is only safe against a *network*
attacker — it does nothing against DNS rebinding, where a malicious web page
the operator visits resolves its own hostname to 127.0.0.1 and drives the
local daemon from the browser. The browser still sends the attacker's
hostname in the Host header, so we reject any request whose Host is not an
allowed loopback name (or the configured bind host). This runs before any
handler and fails closed.

Origin check (cross-origin/CSRF defense): the Host-header allowlist does
*not* stop a same-machine browser tab from making a *direct* cross-origin
request to the API — for that request the Host header legitimately reads
"127.0.0.1:7683" (or whatever the daemon is bound to), because that really
is the target. Only the Origin header — set by the browser to the page that
initiated the request, and not forgeable by that page — reveals that the
caller is a different site. ``origin_middleware`` rejects any /api/ request
whose Origin does not match this server's own origin, and never echoes a
wildcard Access-Control-Allow-Origin (it either omits CORS headers entirely
for non-browser/same-origin requests, or echoes back the exact, verified
origin). This closes the finding where any website the operator visited
could stop the daemon, rewrite its config, delete personas, or read session
history via a simple cross-origin fetch().

Auth: auth_middleware enforces a bearer token on /api/ requests when one is
configured. The CLI now auto-generates and persists a token on first run
(see api/auth.py) even for a loopback bind, so in practice a token is always
present — the "no token configured" branch below only matters for direct,
non-CLI callers that explicitly construct an ApiState with api_token=None.
"""

from __future__ import annotations

from aiohttp import web

# Host names (sans port) that always identify the local machine. A request
# whose Host header resolves to one of these cannot have been smuggled in via
# DNS rebinding, because the browser would have to send the *attacker's*
# hostname. The configured bind host is added to this set at request time.
_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# CORS headers shared by both the preflight response and echoed onto actual
# responses. Access-Control-Allow-Origin is deliberately NOT included here —
# it is only ever set to the verified caller's own Origin, never a constant.
_CORS_METHOD_HEADERS = {
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
}


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


def _expected_origin(request: web.Request) -> str:
    """Return the Origin a legitimate same-origin request would carry.

    By the time this runs, host_allowlist_middleware has already verified
    the Host header names this server (loopback or the configured bind
    host), so "http://" + Host is exactly this API's own origin. The API is
    HTTP-only (no TLS support), so the scheme is always "http".
    """
    return f"http://{request.headers.get('Host', '').strip()}"


@web.middleware
async def origin_middleware(request: web.Request, handler) -> web.Response:
    """Reject cross-origin /api/ requests; never echo a wildcard ACAO.

    Non-browser clients (curl, the menu bar app's urllib-based client,
    server-to-server calls) never send an Origin header, so they pass
    through unaffected — auth_middleware's bearer-token check is what
    protects them. When a browser *does* send Origin, it is compared
    against this server's own origin (see _expected_origin); a mismatch is
    refused outright with 403 rather than merely omitting CORS headers,
    because omitting CORS headers alone does not stop a cross-origin
    request from firing and causing side effects (e.g. a simple POST) — it
    only stops the *response* from being readable. Static UI assets
    (non-/api/ paths) are public and not gated here.
    """
    if not request.path.startswith("/api/"):
        return await handler(request)

    origin = request.headers.get("Origin")
    if origin is not None and origin.rstrip("/").lower() != _expected_origin(request).lower():
        return web.Response(
            text='{"error": "Forbidden: cross-origin request rejected"}',
            status=403,
            content_type="application/json",
        )

    if request.method == "OPTIONS":
        headers = dict(_CORS_METHOD_HEADERS)
        if origin is not None:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Vary"] = "Origin"
        return web.Response(status=204, headers=headers)

    response = await handler(request)
    if origin is not None:
        # Echo back the exact, already-verified origin — never "*". A
        # verified-but-echoed origin is safe here because auth_middleware
        # still requires the bearer token; this only controls whether a
        # legitimate same-origin browser client can read the response.
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


@web.middleware
async def auth_middleware(request: web.Request, handler) -> web.Response:
    """Enforce bearer token authentication when an API token is configured.

    When no token is set, all API requests pass through. In normal CLI
    operation this branch is no longer reachable — start()/api() always
    resolve a token (explicit or auto-generated, see api/auth.py) before the
    server binds — but it remains supported for direct, non-CLI callers that
    explicitly construct an ApiState with api_token=None, and for tests.

    API paths require auth; static file paths (no /api/ prefix) do not, so
    the web UI can always load even if the token is misconfigured.

    The SSE stream (GET /api/events) is opened via the browser's EventSource
    API, which cannot set custom request headers, so it additionally accepts
    the token as a ``?token=`` query parameter. No other endpoint accepts
    the query-parameter form.
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

    # EventSource cannot set headers — allow the token via query string for
    # this one endpoint only.
    if request.path == "/api/events" and request.query.get("token") == token:
        return await handler(request)

    return web.Response(
        text='{"error": "Unauthorized"}',
        status=401,
        content_type="application/json",
    )
