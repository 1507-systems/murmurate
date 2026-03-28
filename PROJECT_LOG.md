<!-- summary: Autonomous AI agent orchestration daemon with plugin architecture, persona system, multi-transport search, and REST API. -->
# Murmurate — Project Log

## 2026-03-28 — CI Fix: macOS-only Tests + Linux Trash Directory

### Problem
CI was broken on main with two separate failures:
1. `test_menubar.py` imported `rumps` (and `murmurate_menubar` which also imports `rumps`) at module level — `rumps` is macOS-only and not installable on the Ubuntu CI runner, causing an `ImportError` that aborted collection.
2. `test_persona_delete` failed because `handle_persona_delete` in the API server called `shutil.move` to `~/.Trash` without creating the directory first — `~/.Trash` does not exist by default on Linux.

### Changes

**PR #10** (`fix/ci-skip-macos-tests`) — `tests/test_menubar.py`:
- Added `pytestmark = pytest.mark.skipif(sys.platform != "darwin", ...)` to skip all tests in the file on Linux
- Guarded `import rumps` and `from murmurate_menubar import ...` with `if sys.platform == "darwin":` blocks so the module can be collected on Linux without an import error
- macOS: all 443 tests still pass; Linux: 40 menubar tests skipped, remaining 403 pass

**PR #11** (`fix/trash-dir-linux`) — `src/murmurate/api/server.py`:
- Added `trash.mkdir(parents=True, exist_ok=True)` in `handle_persona_delete` before `shutil.move` so the `~/.Trash` directory is created on Linux if it doesn't exist

### Status
- Both PRs merged to main
- CI fully green: 403 passed, 40 skipped (macOS-only menubar tests)

## 2026-03-28 — NPM Audit: Brace-Expansion Vulnerability Fix

### What was fixed

Control-UI brace-expansion vulnerability (npm audit).

### Changes

- Updated brace-expansion from 1.1.12 to 1.1.13 in control-ui/package-lock.json via `npm audit fix`
- All 54 tests pass (4 test files)
- Zero vulnerabilities remaining

### Status

- PR #8 merged to main
- Control-UI CI passes ✓
- Python tests pre-existing failures (unrelated to this change)

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

---

## Full Audit Complete — 2026-03-13

### Summary
All functionality tests passing. Security scan clean. Code cleanup complete.
Project declared production-ready at v0.1.0.

### What Was Audited
- Python 3.12+ async codebase, 350 tests via pytest + pytest-asyncio
- Dependencies: aiohttp, aiosqlite, click, tomli-w, scikit-learn
- Security: pip-audit, secrets grep, git history scan, input validation review

### Phase 1: Documentation
- Missing PROJECT_LOG.md — created
- README.md referenced 3 CLI commands that didn't exist (start, install-daemon, uninstall-daemon) — implemented and wired
- stop, history, stats commands were stubs — wired to real backends
- SPEC.md CLI examples used wrong syntax for personas add — fixed
- 5 stale task-reference placeholder comments removed from source

### Phase 2: Functionality + Cleanup
- Tests: 350 passing, 0 failing
- All CLI commands verified functional
- Zero TODO/FIXME/HACK/XXX comments remaining
- Zero unused imports or dead code found
- All placeholder comments removed or replaced with accurate descriptions

### Phase 3: Security
- pip-audit: 0 vulnerabilities (pip upgraded from 25.0.1 to 26.0.1 to clear CVEs)
- No hardcoded secrets in source
- .env and .env.local in .gitignore
- No secrets in git history
- No eval, exec, subprocess, or injection vectors
- os.kill usage limited to daemon lifecycle (appropriate scope)
- User plugin loading via importlib is by design (documented plugin mechanism)

### Outstanding Known Issues (Accepted for v0.1.0)
- total_duration_s in SessionResult is always 0.0 (wall-clock timing not yet implemented)
- robots.txt checking not implemented (config flag exists, behavior is ignore by default per spec)
- Browser transport (Playwright) pool exists but full session execution not wired end-to-end
- murmurate package not on PyPI (pip install murmurate won't work yet — install from source)

### Final State
- Tests: 350 passing, 0 failing
- Security vulnerabilities: 0 (critical/high/moderate)
- Dead code: removed
- Documentation: complete and accurate

---

## 2026-03-18 — Control UI Implementation

### What was built

Web-based control UI for managing Murmurate instances, implemented as:
1. **REST API server** (`src/murmurate/api/`) — embedded aiohttp server that shares the daemon's event loop and state objects
2. **React frontend** (`control-ui/`) — Vite + React + Tailwind CSS v4 single-page application
3. **CLI integration** — `murmurate api` standalone command + `murmurate start --api` flag

### API Server (`src/murmurate/api/`)

- **server.py**: 16 REST endpoints covering all daemon operations
  - `GET /api/status` — daemon state, session counts
  - `POST /api/daemon/stop` — graceful shutdown
  - `GET/POST/PUT/DELETE /api/personas` — full CRUD for personas
  - `GET /api/history` — session history with limit parameter
  - `GET /api/stats` — activity statistics with plugin/transport/daily breakdowns
  - `GET /api/plugins`, `POST /api/plugins/{name}/enable|disable` — plugin management
  - `GET/PUT /api/config` — configuration read and live update (writes config.toml, hot-reloads)
- **middleware.py**: CORS (permissive for local/LAN use) + bearer token auth
- **ApiState**: Bridge object holding references to config, DB, registry, scheduler — no IPC needed
- Serves the built React app as static files, with SPA fallback routing

### React Frontend (`control-ui/`)

- **Dashboard**: Status cards, plugin distribution bars, daily activity chart
- **Personas**: Table view, detail panel with topic tree visualization, create/delete modals
- **History**: Auto-refreshing session table with status badges, transport info, timing
- **Plugins**: Enable/disable toggles, rate limit and transport info, failure tracking
- **Config**: Structured form editor for all config sections, live save to daemon
- **Components**: Card, StatCard, Button, StatusBadge, Modal — reusable dark-themed UI kit
- **API client** (`api.js`): Centralized fetch wrapper with auth, custom base URL support
- **Hooks**: `useApi` and `usePolling` for data fetching with auto-refresh

### CLI Changes

- `murmurate start` gains `--api`, `--api-port`, `--api-host`, `--api-token` flags
- New `murmurate api` command: runs API server standalone (no scheduler) for UI-only mode
- Default API port: 7683

### Architecture Decisions

- API server embedded in daemon process — avoids IPC, shares same event loop and objects
- Bearer token auth — simple, stateless, good enough for LAN/VPN use
- No auth required when bound to 127.0.0.1 (local-only mode)
- Persona deletion uses `~/.Trash/` per project convention (never `rm`)
- Config updates write TOML to disk and reload in memory (equivalent to SIGHUP)
- Static SPA served by the API server itself in production; Vite proxy during dev

### Tests

- **Python API tests** (`tests/test_api_server.py`): 30 tests covering all endpoints, CORS, auth middleware, helper functions
- **React component tests** (`control-ui/src/__tests__/components.test.jsx`): Card, Button, StatusBadge, Modal
- **React API client tests** (`control-ui/src/__tests__/api.test.js`): All API functions, auth, error handling
- **React App tests** (`control-ui/src/__tests__/App.test.jsx`): Navigation, page rendering, daemon status
- **Total**: 380 Python tests passing (350 original + 30 new), 38 frontend tests passing

### Current State

- API server and frontend are fully functional
- Production build: 213KB JS + 18KB CSS (gzipped: 65KB + 4KB)
- No security audit performed yet (would need `/full-audit` before production declaration)

### Next Steps

- macOS menu bar app (rumps) — design brief mentions this as phase 2
- WebSocket/SSE for real-time session updates (currently uses polling)
- mDNS/Bonjour for automatic instance discovery on LAN
- Multi-instance dashboard (single UI managing multiple Murmurate daemons)

---

## Full Audit — v0.2.0 — 2026-03-18

### Summary

Full audit of v0.2.0 (v0.1.0 core + Control UI). Found and fixed 4 security
issues in the API server. All tests passing, zero lint errors, zero
vulnerabilities in dependencies.

### Phase 1: Documentation

- README.md, SPEC.md, PROJECT_LOG.md all accurate and up to date
- Documented features verified in code — all endpoints, CLI flags, plugin system match docs
- No outdated references found

### Phase 2: Functionality

- Python tests: 380 passing, 0 failing (pytest 8.80s)
- React tests: 38 passing, 0 failing (vitest 1.29s)
- Ruff: 0 errors
- ESLint: 0 errors
- React production build: 213KB JS + 18KB CSS (gzipped: 65KB + 4KB)
- No TODO/FIXME/HACK/XXX in source
- CI config updated to include control-ui job (ESLint, vitest, build)

### Phase 3: Code Cleanup

- No dead code or unused imports found
- No unused variables
- Error handling consistent across all API endpoints

### Phase 4: Security

**Issues found and fixed:**

1. **Path traversal in SPA handler** (CRITICAL) — `_make_spa_handler` passed
   user-controlled URL path directly to `Path()` without checking the resolved
   path stayed inside `static_dir`. A request with `../` sequences could read
   arbitrary files. Fixed by resolving the path and checking it starts with
   the static root.

2. **Path traversal via persona name** (HIGH) — Persona CRUD endpoints used
   the URL parameter `{name}` directly in file path construction
   (`personas/{name}.json`). A name like `../../etc/passwd` would escape the
   personas directory. Fixed by adding `_validate_persona_name()` that rejects
   any name not matching `^[a-zA-Z0-9_-]+$`, applied to all persona endpoints
   (detail, create, update, delete).

3. **Unvalidated query parameters** (LOW) — `limit` and `days` query params in
   `/api/history` and `/api/stats` used raw `int()` conversion without bounds.
   Malformed or extreme values could cause errors or resource abuse. Fixed with
   try/except and clamping to sane ranges (limit: 1-10000, days: 1-365).

4. **CI missing control-ui tests** (LOW) — GitHub Actions CI only ran Python
   tests. Added a `control-ui` job for ESLint, vitest, and production build.

**Verified clean:**

- pip-audit: 0 vulnerabilities in project dependencies (aiohttp, aiosqlite, click, tomli-w, scikit-learn)
- npm audit: 0 vulnerabilities in control-ui dependencies
- No hardcoded secrets in source or git history
- .gitignore covers .env, .env.local, local/, node_modules/, dist/
- Bearer token auth enforced on all /api/ endpoints when configured
- CORS permissive by design (documented: local/LAN use case, token is auth boundary)
- Persona deletion uses ~/.Trash/ (no rm)
- No eval/exec/subprocess injection vectors
- User plugin loading via importlib is by-design (documented plugin mechanism)

### Version Bump

- `pyproject.toml`: 0.1.0 -> 0.2.0
- `src/murmurate/__init__.py`: 0.1.0 -> 0.2.0
- API `/api/status` version: 0.1.0 -> 0.2.0

### Final State

- Python tests: 380 passing, 0 failing
- React tests: 38 passing, 0 failing
- Lint errors: 0 (ruff + ESLint)
- Security vulnerabilities: 0
- Tagged: v0.2.0-audit-clean

---

## 2026-03-22 — macOS Menu Bar App (Control UI Phase 2)

### What was built

macOS menu bar app using rumps (Ridiculously Uncomplicated macOS Python Statusbar apps) that provides tray-level control of the Murmurate daemon without opening a browser.

### Files added

- **`menubar/murmurate_menubar.py`** — Complete menu bar application (~360 lines)
- **`menubar/run.sh`** — Launch script with auto-install of rumps
- **`menubar/requirements.txt`** — Python dependency (rumps>=0.4.0)
- **`menubar/setup.py`** — py2app configuration for building standalone Murmurate.app bundle
- **`tests/test_menubar.py`** — 40 tests covering all components

### Features

- **Status indicator**: Menu bar shows running (triangle), stopped (square), or error (warning) symbols
- **Live polling**: Fetches daemon status every 10 seconds via REST API (background thread, non-blocking)
- **Session counts**: Today's total sessions, completed, and failed counts displayed in menu
- **Persona list**: Submenu showing all personas with session counts, topic counts, and seed topics
- **Recent sessions**: Last 5 sessions with status icons (checkmark/cross), timestamps, persona, and plugin
- **Quick controls**: Stop daemon (with confirmation dialog), open web dashboard in browser
- **Connection settings**: Configurable API endpoint via dialog or environment variables
- **Auth support**: Bearer token auth via MURMURATE_API_TOKEN environment variable
- **Environment configuration**: MURMURATE_API_HOST, MURMURATE_API_PORT, MURMURATE_API_TOKEN, MURMURATE_POLL_INTERVAL
- **Standalone packaging**: py2app setup.py for building .app bundle (LSUIElement=True, no Dock icon)

### Architecture decisions

- **rumps** chosen for menu bar framework — lightweight, pure-Python, well-suited for status-bar-only apps
- **urllib** used for API calls instead of requests/aiohttp — avoids adding dependencies beyond rumps
- **Background threads** for API polling to keep the UI responsive (rumps runs on the main thread)
- **No IPC with daemon** — connects via the same REST API as the web dashboard
- **Environment variables** for config rather than a config file — simpler for a companion utility

### How to run

1. Direct: `cd menubar && ./run.sh`
2. With custom endpoint: `MURMURATE_API_HOST=192.168.1.5 ./run.sh`
3. As .app bundle: `cd menubar && pip3 install py2app && python3 setup.py py2app` (output in dist/)

### Tests

- 40 new tests in `tests/test_menubar.py`
- Tests cover: AppConfig, DaemonStatus, PersonaSummary dataclasses, ApiClient with live mock HTTP server, environment variable config, status symbols, MurmurateMenuBar UI state updates
- Total project tests: 420 Python passing (380 existing + 40 new)

### Current state

- Menu bar app fully functional and tested
- Not yet production-audited (would need `/full-audit` before declaring production-ready)

---

## 2026-03-22 — Real-Time SSE + mDNS LAN Discovery

### What was built

Two features listed as next steps in the v0.2.0 log:

1. **Server-Sent Events (SSE) for real-time session updates** — replaces polling for live session data.
2. **mDNS/Bonjour advertisement** — the API server advertises itself on the LAN so the control UI can discover Murmurate without manual IP entry.

### Backend changes

#### `src/murmurate/api/events.py` (new)
- `EventBus` class: holds a set of per-subscriber `asyncio.Queue` instances.
- `broadcast(event_type, data)`: non-blocking push to all connected queues. Full queues (slow consumers) silently drop the event.
- `handle_sse(request)`: aiohttp `StreamResponse` handler registered at `GET /api/events`. Sends an initial `connected` event, then streams events as they arrive. Sends `: heartbeat\n\n` comments every 15 seconds to keep proxies alive.
- `MAX_SSE_CONNECTIONS = 50`: hard cap; returns 503 when exceeded.
- SSE chosen over WebSocket because session updates are unidirectional (server → client only), SSE has built-in browser reconnect, and it works over plain HTTP with no extra dependencies.

#### `src/murmurate/api/mdns.py` (new)
- `MdnsAdvertiser` class: wraps the `zeroconf` library (already present on the system as an esphome transitive dep).
- Advertises service type `_murmurate._tcp.local.` with TXT records for `version`, `api_path`, `ui_path`, and `hostname`.
- `start()` / `stop()` lifecycle. Both are no-ops (with logged warnings) if `zeroconf` is not installed or if registration fails — never crashes the daemon.
- `_get_local_ip()`: uses a UDP connect trick to find the primary LAN interface IP.
- `zeroconf>=0.80` added to `pyproject.toml` as `[project.optional-dependencies.discovery]`.

#### `src/murmurate/api/server.py` (modified)
- `ApiState` gains `event_bus: EventBus` attribute (always constructed, even before any client connects).
- `create_app()` registers `GET /api/events` using `state.event_bus.handle_sse`.
- `GET /api/status` now includes `sse_connections` count.
- Version string bumped to `0.3.0`.

#### `src/murmurate/scheduler/scheduler.py` (modified)
- Constructor gains optional `event_bus: EventBus | None = None` parameter.
- After `log_session_start`: broadcasts `session_started` event.
- After `log_session_complete`: broadcasts `session_completed` event with query/browse counts and new subtopics.
- On exception: broadcasts `session_failed` event with error string.
- Import uses `TYPE_CHECKING` guard so there is zero runtime cost when the API is not loaded.

#### `src/murmurate/cli.py` (modified)
- `_run_with_api()`: creates `ApiState` first so the `event_bus` exists before the `Scheduler` is built; passes `event_bus` to `Scheduler` constructor; starts `MdnsAdvertiser` after the HTTP server is listening; stops it in the `finally` block.
- `_run_api_only()`: starts and stops `MdnsAdvertiser` for standalone API-only mode.

### Frontend changes

#### `control-ui/src/hooks/useSSE.js` (new)
- `useSSE({ onEvent, enabled })`: opens an `EventSource` to `/api/events`, tracks `connected` state and `lastEvent`. Calls `onEvent` on every JSON event. Auto-reconnects (browser native). No-op when `EventSource` is unavailable.
- `useSessionEvents(maxEvents)`: wraps `useSSE` to accumulate `session_started` / `session_completed` / `session_failed` events into a bounded list (newest first). Exposes `clearEvents()`.

#### `control-ui/src/pages/Dashboard.jsx` (modified)
- On `session_completed` or `session_failed` SSE events calls `refreshStatus()` so the "Sessions Today" counter updates immediately without waiting for the next poll.
- Shows a pulsing green `Live` / grey `Polling` indicator next to the page title.

#### `control-ui/src/pages/History.jsx` (modified)
- Live events appear in a "Live Events" card above the history table instantly when the scheduler fires.
- Polling interval relaxed to 30 s (was 10 s) because SSE covers real-time needs.
- Shows SSE `Live` / `Polling` indicator in the page header.
- `clearEvents` button dismisses the live panel.

### Tests added

| File | New tests |
|------|-----------|
| `tests/test_events.py` | 18 — EventBus unit tests + SSE HTTP endpoint tests |
| `tests/test_mdns.py` | 9 — MdnsAdvertiser lifecycle + _get_local_ip fallback |
| `control-ui/src/__tests__/useSSE.test.js` | 16 — useSSE and useSessionEvents hooks |

### Test results

| Suite | Before | After |
|-------|--------|-------|
| Python (pytest) | 420 | 443 |
| Frontend (vitest) | 38 | 54 |
| Lint (ruff) | 0 errors | 0 errors |
| Lint (ESLint) | 0 errors | 0 errors |

---

## Full Audit — v0.3.0 — 2026-03-22

### Summary

Full audit of v0.3.0 (v0.2.0 + menu bar app + SSE events + mDNS discovery).
Found and fixed 6 issues across lint and versioning. All tests passing, zero
lint errors, zero vulnerabilities in project dependencies, no secrets in source
or git history.

### Phase 1: Documentation

- README.md: accurate for existing features (does not yet mention menu bar, SSE, or mDNS — these are advanced/optional features, documented in PROJECT_LOG)
- SPEC.md: accurate
- PROJECT_LOG.md: updated with v0.3.0 audit entry

### Phase 2: Functionality

- Python tests: 443 passing, 0 failing (pytest 13.24s)
- React tests: 54 passing, 0 failing (vitest)
- Ruff: 0 errors (src/, tests/, menubar/, scripts/)
- ESLint: 0 errors
- No TODO/FIXME/HACK/XXX in source

### Phase 3: Code Cleanup

Issues found and fixed:

1. **Unused imports in test_menubar.py** — `MagicMock` and `MurmurateMenuBar` imported but unused. Fixed by ruff --fix.
2. **Module-level import not at top of file in test_menubar.py** (E402) — `from murmurate_menubar import ...` was after helper function. Moved import to right after `sys.path.insert` with `# noqa: E402`.
3. **Unused imports in murmurate_menubar.py** — `subprocess` and `sys` imported but unused. Fixed by ruff --fix.
4. **Unnecessary f-string in murmurate_menubar.py** — `f"Status: Disconnected"` had no interpolation. Changed to plain string.
5. **Version inconsistency** — `pyproject.toml` and `__init__.py` still at 0.2.0 while `server.py` was bumped to 0.3.0 and `mdns.py` defaulted to 0.2.0. Synchronized all to 0.3.0.

### Phase 4: Security

**Verified clean:**

- pip-audit: 0 vulnerabilities in project dependencies (flagged items are system-wide packages unrelated to murmurate)
- npm audit: 0 vulnerabilities in control-ui dependencies
- No hardcoded secrets, API keys, tokens, passwords, or personal data in source
- No sensitive files in git history (critical for PUBLIC repo)
- .gitignore covers .env, .env.local, local/, node_modules/, dist/
- Path traversal protections from v0.2.0 audit still in place (SPA handler, persona name validation)
- SSE connection cap (MAX_SSE_CONNECTIONS=50) prevents memory exhaustion from idle clients
- SSE queue bounded (maxsize=100 per subscriber) — full queues drop events rather than blocking
- mDNS advertiser is a no-op when zeroconf is not installed — never crashes the daemon
- Bearer token auth still enforced on all /api/ endpoints when configured
- CORS permissive by design (documented: local/LAN use case)
- Menu bar app reads API token only from environment variable (no file storage of secrets)

### Version Bump

- `pyproject.toml`: 0.2.0 -> 0.3.0
- `src/murmurate/__init__.py`: 0.2.0 -> 0.3.0
- `src/murmurate/api/server.py` handle_status: already 0.3.0
- `src/murmurate/api/mdns.py` MdnsAdvertiser default: 0.2.0 -> 0.3.0

### Final State

- Python tests: 443 passing, 0 failing
- React tests: 54 passing, 0 failing
- Lint errors: 0 (ruff + ESLint)
- Security vulnerabilities: 0 (in project dependencies)
- Tagged: v0.3.0-audit-clean

---

## 2026-03-22 — Branch Protection Enabled

### What was done

Enabled GitHub branch protection on the `main` branch of the public 1507-systems/murmurate repository.

### Configuration

- **Require status checks**: Enabled (strict mode)
- **Require PRs**: Enabled (0 required approvals for now, can be increased later)
- **Enforce on admins**: Disabled
- **Restrictions**: None (all team members can push via PR)

The repository already has CI configured (.github/workflows), so branch protection integrates seamlessly with the existing test pipeline.

### Verification

Verified via `gh api repos/1507-systems/murmurate/branches/main/protection`:
- Required status checks: strict=true, contexts=[] (checks will auto-populate when CI runs)
- Required pull request reviews: required_approving_review_count=0
- All other protections: default (no force-push, no deletions, linear history disabled)

---

## 2026-03-27 — v0.4.0 Re-Audit (post log_file fix)

### Trigger
11 commits merged after v0.3.0-audit-clean tag, including the `log_file` None fix (#6), CI peer dependency fix (#5), bandit warning suppressions (#3, #4), and security lint fixes (#2).

### Results

| Check | Result |
|-------|--------|
| Python tests (`pytest tests/ -x -q`) | 443 passed |
| React tests (`vitest run`, control-ui) | 54 passed |
| bandit (`-r src/`) | 0 Medium/High; 39 Low (B110 try-except-pass, intentional) |
| shellcheck (menubar/run.sh, scripts/install-macos.sh) | Clean |
| npm audit (`--omit=dev`, control-ui) | 0 vulnerabilities |
| Secrets scan | Clean (only test fixture dummies) |
| Private data scan (PUBLIC repo) | Clean — no real IPs, emails, keys |
| TODO/FIXME/HACK/XXX | None in source |

### Outcome
- Tagged `v0.4.0-audit-clean` on main
- Total test count: 497 (443 Python + 54 React)
