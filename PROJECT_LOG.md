# Murmurate — Project Log

## 2026-03-13 — v0.1.0 Initial Implementation

### What was built

Complete v0.1.0 implementation of Murmurate, a privacy tool that generates realistic decoy internet activity to obscure real browsing patterns.

### Core components implemented

- **Scheduler** (`src/murmurate/scheduler/`): Poisson-distributed session timing with circadian rhythm modeling, quiet hours, burst mode, and per-domain rate limiting.
- **Persona Engine** (`src/murmurate/persona/`): Topic tree evolution via TF-IDF keyword extraction, weighted branch selection, fingerprint generation with platform-consistent profiles.
- **Transport Layer** (`src/murmurate/transport/`): HTTP transport using aiohttp with retry/backoff, DNS failure tracking, bot challenge detection. Browser transport interface defined (Playwright integration pending).
- **Plugin System** (`src/murmurate/plugins/`): Base plugin interface with bundled plugins for DuckDuckGo, Wikipedia, Google, YouTube, Amazon, Reddit, and Bing. User plugin discovery from config directory.
- **Database** (`src/murmurate/database.py`): Async SQLite via aiosqlite for session logging and rate limit tracking with retry-on-lock.
- **Configuration** (`src/murmurate/config.py`): TOML-based config with three-tier resolution (CLI flag, env var, default path).
- **CLI** (`src/murmurate/cli.py`): Click-based CLI with commands: `run`, `start`, `stop`, `status`, `history`, `stats`, `personas`, `plugins`, `install-daemon`, `uninstall-daemon`.
- **Daemon Lifecycle** (`src/murmurate/daemon/`): PID file management, signal handlers (SIGTERM/SIGINT/SIGHUP), launchd plist and systemd unit generation.
- **Logging** (`src/murmurate/log.py`): Structured JSON or text log output.

### Architecture decisions

- Single async Python process — no IPC, no external dependencies beyond aiohttp and aiosqlite.
- Personas are append-only topic trees stored as JSON — safe for multi-machine sync via iCloud/Syncthing.
- Each persona gets a consistent fingerprint profile (UA, screen res, WebGL, timezone, fonts) to simulate distinct users.
- Plugins declare their own rate limits, transport preferences, and domain lists.
- The scheduler does not self-daemonize — relies on launchd/systemd for process management.

### CLI audit fixes (this session)

- Wired `stop` command to `daemon.lifecycle.stop_daemon()` (was a placeholder).
- Added `start` command for daemon foreground mode with PID file management.
- Added `install-daemon` and `uninstall-daemon` commands for launchd/systemd service installation.
- Wired `history` command to query session database.
- Wired `stats` command to compute activity statistics from session database.
- Removed stale task-reference placeholder comments from cli.py, scheduler.py, and http.py.
- Updated SPEC.md CLI examples to match actual `personas add` syntax.
- Updated README.md Quick Start section.

### Current state

- All CLI commands are functional (no remaining placeholders).
- Test suite passes.
- Not yet production-audited — `/full-audit` has not been run.

### Next steps

- Per-session wall-clock timing (total_duration_s is currently 0.0).
- robots.txt checking (config flag exists but not implemented).
- Browser transport (Playwright) integration.
- Full audit before any production declaration.
