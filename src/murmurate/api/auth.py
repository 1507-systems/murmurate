"""
auth.py — API bearer-token generation and persistence.

Historically the control API allowed "no token" whenever it was bound to
loopback, relying on the Host-header allowlist (host_allowlist_middleware)
as the sole defense. That stops DNS rebinding but does nothing against a
same-machine browser tab making a *direct* cross-origin request to
127.0.0.1:7683 — the Host header for such a request is legitimately
"127.0.0.1:7683", so the allowlist happily lets it through. Combined with
the CORS middleware's old wildcard Access-Control-Allow-Origin, any website
the operator visited could drive the daemon: stop it, rewrite its config,
delete personas, or read session history (see origin_middleware in
middleware.py for the other half of this fix).

The fix here is to never run with no token at all: the CLI now auto-
generates one on first run and persists it to disk so the bundled clients
(the menu bar app, the control-ui dev proxy) can read it without the
operator manually configuring anything. Losing/rotating the token is as
simple as deleting the file — a new one is generated on the next start.
"""

from __future__ import annotations

import secrets
import stat
from pathlib import Path

# Stored alongside config.toml, personas/, etc. in the resolved config
# directory (see murmurate.config.resolve_config_dir).
TOKEN_FILENAME = "api_token"  # nosec B105 — a filename, not a credential value


def get_or_create_api_token(config_dir: Path) -> str:
    """Return the persisted API token for config_dir, generating one if absent.

    The token lives at ``config_dir/api_token`` as a single line of text. Its
    sensitivity is equivalent to a password — anyone who can read it can
    stop the daemon, rewrite its config, or read full browsing history — so
    the file is created with 0600 permissions (owner read/write only).

    Safe to call on every API startup: an existing, non-empty token file is
    read and returned as-is (so the value stays stable across restarts,
    which is what lets the menu bar app and control-ui dev proxy keep
    working without reconfiguration). A missing or empty/corrupt file gets
    a fresh cryptographically random token.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    token_file = config_dir / TOKEN_FILENAME

    if token_file.exists():
        existing = token_file.read_text().strip()
        if existing:
            return existing
        # Empty/corrupt file — fall through and regenerate below.

    token = secrets.token_urlsafe(32)
    token_file.write_text(token + "\n")
    # Owner read/write only. Set explicitly (rather than relying on umask)
    # so the permission holds regardless of the process's umask.
    token_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return token
