# Murmurate Control UI — Design Brief

**Status:** Brainstorming paused — resume with `/brainstorming` when ready.

**Date:** 2026-03-14

---

## What the user wants

1. **macOS menu bar app** — lightweight status/control from the menu bar (using `rumps` or similar)
2. **Web UI** — cross-platform browser-based dashboard for richer interaction
3. **Remote control** — both UIs should be able to connect to Murmurate instances on other machines across LAN, VPN, or overlay networks (e.g., control headless RogueNode from a laptop)

---

## Current state of the codebase (relevant to this feature)

- **No HTTP API exists** — the daemon is a single async Python process controlled via CLI, OS signals (SIGTERM/SIGHUP), and file I/O
- **Database:** async SQLite (`state.db`) stores session history and rate limit data — queryable via `StateDB` class
- **Config:** TOML file, hot-reloadable via SIGHUP signal
- **Personas:** JSON files in `~/.config/murmurate/personas/`, one per persona
- **Daemon lifecycle:** PID file based, SIGTERM to stop, SIGHUP to reload
- **No real-time push** — UI must poll or we need to add WebSocket/SSE

---

## Key design questions to resolve (brainstorming paused here)

1. **API server architecture** — embed an HTTP API server inside the daemon process (aiohttp already a dependency), or run a separate API server process?
2. **Authentication** — remote access needs auth. API key? mTLS? Bearer token? How lightweight vs. how secure?
3. **Discovery** — how do clients find instances on the LAN? mDNS/Bonjour? Manual IP:port config? Both?
4. **Menu bar app scope** — full control surface, or just status + start/stop + "open web UI in browser"?
5. **Web UI tech stack** — vanilla HTML/JS served by the API? A JS framework? How heavy?
6. **Config editing** — should the UI allow editing config.toml, or just display it? Full CRUD on personas?
7. **Real-time updates** — polling interval sufficient, or add WebSocket/SSE for live session feed?
8. **Multi-instance dashboard** — one web UI showing all connected instances, or one UI per instance?

---

## Likely architecture (pre-decision sketch)

```
┌─────────────────────────────────────────────┐
│  Murmurate Daemon (existing async process)  │
│                                             │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │Scheduler│  │ Personas │  │  StateDB   │  │
│  └────┬────┘  └────┬─────┘  └─────┬─────┘  │
│       │            │              │         │
│  ┌────┴────────────┴──────────────┴──────┐  │
│  │         NEW: API Server (aiohttp)     │  │
│  │  REST endpoints + optional WebSocket  │  │
│  │  Listens on 0.0.0.0:<port>            │  │
│  │  Bearer token auth for remote access  │  │
│  └───────────────┬───────────────────────┘  │
└──────────────────┼──────────────────────────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
   ┌────┴───┐ ┌───┴────┐ ┌───┴──────┐
   │Menu Bar│ │ Web UI │ │ Remote   │
   │  App   │ │(browser│ │ Client   │
   │(rumps) │ │ local) │ │(browser) │
   └────────┘ └────────┘ └──────────┘
```

All three clients talk to the same REST API. The web UI is static HTML/JS served by the API server itself. The menu bar app calls the API via localhost. Remote clients connect over LAN/VPN.

---

## Resume instructions

When resuming this brainstorm:
1. Read this file for context
2. Continue from "Ask clarifying questions" (task #32 in the brainstorming checklist)
3. The visual companion was offered but user deferred — re-offer if relevant
4. Walk through the 8 design questions above one at a time
