"""
tests/test_auth.py — Tests for API token generation/persistence (api/auth.py).

Covers the fix for the "no token on loopback" finding: the daemon must
always have a bearer token, auto-generated on first run and stable across
restarts so the bundled clients (menu bar app, control-ui dev proxy) can
keep authenticating without the operator doing anything manual.
"""

from __future__ import annotations

import stat

from murmurate.api.auth import TOKEN_FILENAME, get_or_create_api_token


def test_generates_token_when_missing(tmp_path):
    """A fresh config dir with no token file gets a newly generated token."""
    token = get_or_create_api_token(tmp_path)
    assert token
    assert (tmp_path / TOKEN_FILENAME).exists()


def test_token_is_persisted_to_disk(tmp_path):
    """The generated token should be written to config_dir/api_token."""
    token = get_or_create_api_token(tmp_path)
    on_disk = (tmp_path / TOKEN_FILENAME).read_text().strip()
    assert on_disk == token


def test_token_file_permissions_owner_only(tmp_path):
    """The token file must be readable/writable by the owner only (0600) —
    it is as sensitive as a password (stop daemon, rewrite config, read
    full browsing history)."""
    get_or_create_api_token(tmp_path)
    mode = (tmp_path / TOKEN_FILENAME).stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_token_is_stable_across_calls(tmp_path):
    """Calling twice (e.g. daemon restart) must return the same token, not
    silently rotate it and break already-configured clients."""
    first = get_or_create_api_token(tmp_path)
    second = get_or_create_api_token(tmp_path)
    assert first == second


def test_token_is_reasonably_random_and_long(tmp_path):
    """Two different config dirs should never collide on the same token, and
    the token should be long enough to resist guessing."""
    tokens = {get_or_create_api_token(tmp_path / f"dir{i}") for i in range(5)}
    assert len(tokens) == 5
    for token in tokens:
        assert len(token) >= 32


def test_creates_config_dir_if_missing(tmp_path):
    """config_dir need not exist yet — this is called before anything else
    has necessarily created it."""
    nested = tmp_path / "does" / "not" / "exist" / "yet"
    assert not nested.exists()
    token = get_or_create_api_token(nested)
    assert token
    assert nested.is_dir()


def test_regenerates_on_empty_file(tmp_path):
    """A zero-byte/whitespace-only token file (corrupt or truncated write)
    should be treated as absent and regenerated, not returned as-is."""
    tmp_path.mkdir(exist_ok=True)
    token_file = tmp_path / TOKEN_FILENAME
    token_file.write_text("   \n")

    token = get_or_create_api_token(tmp_path)
    assert token.strip()
    assert token_file.read_text().strip() == token


def test_reads_existing_token_verbatim(tmp_path):
    """An existing, non-empty token file should be returned as-is (surrounding
    whitespace stripped) rather than being overwritten."""
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / TOKEN_FILENAME).write_text("preexisting-token-value\n")

    token = get_or_create_api_token(tmp_path)
    assert token == "preexisting-token-value"
