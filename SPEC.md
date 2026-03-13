# Murmurate

**A privacy tool that generates realistic decoy internet activity to obscure real browsing patterns.**

Named after murmuration — the swirling flocks of starlings where no individual bird can be tracked. Murmurate does the same for your digital footprint: buries your real activity in a coherent, realistic stream of noise that's statistically hard to separate from signal.

---

## Table of Contents

- [Overview](#overview)
- [Goals & Non-Goals](#goals--non-goals)
- [Architecture](#architecture)
- [Core Components](#core-components)
  - [Scheduler & Timing Model](#scheduler--timing-model)
  - [Persona Engine](#persona-engine)
  - [Transport Layer](#transport-layer)
  - [Site Plugins](#site-plugins)
- [Configuration](#configuration)
- [Multi-Machine Sync](#multi-machine-sync)
- [CLI Interface](#cli-interface)
- [Privacy & Ethics](#privacy--ethics)
- [Inspiration & Prior Art](#inspiration--prior-art)
- [Tech Stack](#tech-stack)

---

## Overview

Existing privacy noise tools (Chaff, Noisy, TrackMeNot) share a critical weakness: they generate obviously artificial traffic. Random noun searches at fixed intervals are trivially filterable by any moderately sophisticated observer. ISPs with baseline data can statistically subtract uniform noise from real patterns.

Murmurate takes a different approach: **persona-driven, temporally realistic browsing sessions** that evolve over time. Instead of random queries, it simulates coherent research arcs — a fake interest in woodworking that progresses from "beginner projects" to "Stanley No. 4 restoration" over weeks. Instead of fixed intervals, sessions follow Poisson distributions with circadian patterns matching real human behavior.

The result: noise that looks, statistically, like signal.

## Goals & Non-Goals

### Goals

- Generate decoy internet activity that is statistically difficult to distinguish from real browsing
- Support persona-driven topic evolution that produces coherent, realistic search sessions
- Provide both lightweight HTTP and full browser-based traffic generation
- Run as a background daemon with configurable schedules, or on-demand via CLI
- Support multi-machine deployment with shared configuration via cloud sync (iCloud, Syncthing, etc.)
- Offer a plugin architecture for adding new target sites
- Ship with sensible, conservative defaults that work out of the box

### Non-Goals

- **Anonymity** — Murmurate does not hide your IP address. Pair with a VPN if that's your goal.
- **Ad blocking** — Use AdNauseam for ad profile poisoning. Murmurate focuses on search and browsing noise.
- **Fingerprint randomization** — This is a browser-engine-level problem. Use dedicated tools (Brave, Tor Browser, FPRandom).
- **Data scraping** — Search results are parsed for persona evolution only, never stored or transmitted.
- **DDoS or abuse** — Rate limits are enforced. Traffic volume is modest by design.

## Architecture

```
+--------------------------------------------------+
|                  CLI / Daemon                     |
|             (Click + launchd plist)              |
+--------------------------------------------------+
|                   Scheduler                       |
|        (Poisson timing + circadian model)        |
+----------+------------------------+--------------+
|  Persona |    Transport Layer     |    Plugin    |
|  Engine  |  +--------+--------+  |    Registry  |
|          |  | HTTP   | Browser|  |              |
|          |  |(aiohttp)|(Playwright)|             |
|          |  +--------+--------+  |              |
+----------+------------------------+--------------+
|            Config (shared / local)               |
|       ~/.config/murmurate/ or custom             |
+--------------------------------------------------+
```

- Single async Python process using `asyncio`
- Scheduler fires "sessions" — each session is a persona doing a coherent research arc on a specific site
- Transport chosen per-session: lightweight HTTP for bulk noise, Playwright for deep browsing that needs to look human
- All components communicate in-process via async interfaces — no IPC, no queues, no external dependencies

## Core Components

### Scheduler & Timing Model

The scheduler is what makes traffic look human rather than robotic.

**Timing model:**
- Base rate: configurable sessions-per-hour (default: 3-6)
- Inter-session gaps follow a Poisson distribution — irregular intervals, not clockwork
- Circadian overlay: activity follows a bell curve matching the user's configured timezone and "active hours" (default: 7am-11pm, peak at 10am and 8pm)
- Weekend/weekday variance: slightly different patterns (more leisure browsing on weekends, more "work research" on weekdays)

**Session scheduling:**
- Priority queue of upcoming sessions
- Each session has: persona, topic branch, target site, transport type, estimated duration
- Sessions can overlap (real humans have multiple tabs open) — async handles this naturally
- Burst mode: occasionally clusters 2-3 quick searches in rapid succession (simulates "I just thought of something")

**Rate limiting & safety:**
- Per-domain rate limits to avoid triggering CAPTCHAs or bans (configurable per plugin)
- Global bandwidth cap (configurable) — don't saturate the connection
- Backoff on HTTP errors (429, 503) with jitter
- Quiet hours: zero activity during configured sleep window

### Persona Engine

Personas are the core differentiator — what makes this noise hard to filter out.

**Persona structure:**
- Each persona has a name (for config/logging only), seed interests, and an evolving topic tree
- Topic trees start from user-provided seeds (e.g., "woodworking") and branch into subtopics over time ("hand planes" → "Stanley No. 4 restoration" → "where to buy japanning lacquer")
- Evolution is deterministic from the seed + a drift parameter — same seed produces the same tree across machines (important for sync)

**Session generation:**
- Scheduler picks a persona, picks a branch of their topic tree, generates a "research session" — a sequence of 3-8 queries that follow a logical progression
- Sessions have realistic dwell patterns: search → click result → read (30-120s) → refine query → click another result → done
- Some sessions are shallow (quick lookup), some are deep dives (20+ minutes across multiple sites)

**Evolution over time:**
- After each session, the topic tree grows — new subtopics discovered from actual search results get added as branches
- Personas develop "expertise" — early queries are broad ("woodworking for beginners"), later ones are specific ("mortise gauge setup for through tenons")
- Drift parameter controls how fast personas evolve and how far they stray from seeds
- Persona state lives in `personas/` directory (JSON files), syncs across machines

**Built-in topic pools:**
- If the user provides no seeds, Murmurate draws from curated pools: hobbies, academic subjects, shopping categories, travel destinations, professional skills
- Mix of evergreen topics and trending/seasonal ones

### Transport Layer

Two transports behind a common async interface.

**Abstract interface:**
```python
class Transport(ABC):
    async def execute_session(self, session: BrowsingSession) -> SessionResult
```

**HttpTransport (aiohttp):**
- Lightweight, low resource — used for ~70% of sessions by default
- Rotates User-Agent strings from a realistic, auto-updated pool
- Follows redirects, parses HTML responses to extract links for "click-through"
- Cannot execute JavaScript — sites that require JS get escalated to BrowserTransport
- Good for: search queries, Wikipedia, Reddit, news sites, Amazon product browsing

**BrowserTransport (Playwright async):**
- Full Chromium engine, indistinguishable from real browsing
- Handles JS-heavy sites, SPAs, infinite scroll
- Simulates human behavior: mouse movements, scroll patterns, realistic typing speed with typos/corrections
- Resource-heavy — used for ~30% of sessions by default, configurable
- Browser instance pooling: reuses contexts to avoid constant startup cost, rotates profiles periodically
- Good for: YouTube (watch partial videos), Google with JS, sites with bot detection

**Transport selection:**
- Plugin declares its preferred transport (some sites require Browser)
- Scheduler respects the split ratio from config
- Fallback: if HTTP gets a bot challenge, retry with Browser

### Site Plugins

Each target site is a plugin that knows how to construct queries and navigate that site realistically.

**Plugin interface:**
```python
class SitePlugin(ABC):
    name: str
    domains: list[str]
    preferred_transport: TransportType  # HTTP, BROWSER, or EITHER
    rate_limit_rpm: int

    async def generate_query(self, topic: str, depth: int) -> str
    async def execute_search(self, query: str, transport: Transport) -> list[SearchResult]
    async def browse_result(self, result: SearchResult, transport: Transport) -> BrowseAction
```

**Bundled plugins:**
- `google` — web search, follows results, handles "People also ask"
- `bing` — web search
- `duckduckgo` — web search (HTTP-friendly, no JS required)
- `youtube` — search + partial video watching (Browser transport required)
- `amazon` — product search, browse listings, read reviews
- `reddit` — subreddit browsing, post reading, thread following
- `wikipedia` — article reading, link following (pure HTTP, very lightweight)

**Plugin discovery:**
- Bundled plugins in `murmurate/plugins/`
- User plugins in `{config_dir}/plugins/` — drop a `.py` file, auto-discovered at startup
- Plugins declare their own rate limits, preferred transport, and domain list
- Enable/disable and override settings via config

**Community contribution:** public repo — PRs welcome for new site plugins (eBay, Zillow, Stack Overflow, news sites, etc.)

## Configuration

All configuration lives in a single `config.toml` file within the config directory.

```toml
[scheduler]
sessions_per_hour = { min = 3, max = 8 }
active_hours = { start = "07:00", end = "23:00", timezone = "America/New_York" }
peak_hours = ["10:00", "20:00"]
quiet_hours = { start = "23:30", end = "06:30" }
burst_probability = 0.15

[rate_limits]
global_bandwidth_mbps = 5
default_per_domain_rpm = 10

[transport]
browser_ratio = 0.3
browser_pool_size = 2
headless = true
typing_wpm = { min = 40, max = 80 }
mouse_jitter = true

[personas]
auto_generate_count = 3
drift_rate = 0.1
max_tree_depth = 5

[plugins]
enabled = ["google", "duckduckgo", "youtube", "amazon", "reddit", "wikipedia"]
disabled = ["bing"]

[plugins.google]
rate_limit_rpm = 8

[plugins.youtube]
max_watch_seconds = 120
```

## Multi-Machine Sync

Murmurate supports running on multiple machines with shared configuration — a federated model where each machine runs independently but shares persona state.

**Config directory resolution (first match wins):**
1. `--config-dir` CLI flag
2. `MURMURATE_CONFIG` environment variable
3. `~/.config/murmurate/`

**Directory layout:**
```
{config_dir}/
├── config.toml               # all settings (syncs)
├── personas/                  # persona seeds + evolved state (syncs)
│   ├── woodworker.json
│   ├── amateur-chef.json
│   └── _auto_generated/      # from topic pools
├── plugins/                   # user site plugins (syncs)
│   └── zillow.py
└── local/                     # machine-specific, excluded from sync
    ├── state.db               # SQLite — session log, rate limit counters
    ├── daemon.pid
    └── murmurate.log
```

**Sync behavior:**
- `config.toml`, `personas/`, `plugins/` are safe to sync (iCloud, Syncthing, Dropbox, git)
- `local/` is machine-specific — `.gitignore`d, excluded from cloud sync via `.nosync` marker
- Persona evolution conflict resolution: last-write-wins on JSON files. Since evolution is additive (topic trees only grow), conflicts are rare and harmless — worst case, two machines add different branches and both survive on next sync
- Each machine stamps session log entries with a machine ID (hostname by default, configurable) for audit

## CLI Interface

```bash
# On-demand session
murmurate run --sessions 10

# Start daemon
murmurate start

# Stop daemon
murmurate stop

# Status (running sessions, personas, next scheduled)
murmurate status

# Generate and install launchd plist (macOS)
murmurate install-daemon

# Uninstall daemon
murmurate uninstall-daemon

# Point at custom config directory (e.g., iCloud)
murmurate start --config-dir "~/Library/Mobile Documents/com~apple~CloudDocs/murmurate"

# List personas and their topic trees
murmurate personas list

# Add a new persona seed
murmurate personas add --name "gardener" --seeds "container gardening,herb growing"

# Show session history
murmurate history --last 24h

# Plugin management
murmurate plugins list
murmurate plugins info google
```

## Privacy & Ethics

**Murmurate is a defensive privacy tool.** It generates noise to protect the user's own data.

**What it is NOT:**
- A DDoS tool — rate limits are enforced, traffic volume is modest
- A scraping framework — it reads pages for navigation, doesn't extract/store data
- An anonymity tool — it doesn't hide your IP; pair with a VPN if that's your goal

**Responsible defaults:**
- Conservative rate limits out of the box — won't trigger abuse detection
- `robots.txt` awareness — plugins respect crawl directives by default (overridable)
- Bandwidth cap prevents saturating connections
- No data exfiltration — search results are parsed for persona evolution only, never stored or transmitted

**Legal disclaimer:**
- Generating automated traffic may violate Terms of Service of some services
- Users are responsible for compliance with local laws and service terms
- Murmurate is provided as-is for privacy research and personal use

**Transparency:**
- Fully open source (MIT license)
- No telemetry, no phone-home, no analytics
- All activity is logged locally for the user's own audit

## Inspiration & Prior Art

Murmurate builds on ideas from the following projects and research:

| Project | What We Learned | URL |
|---------|----------------|-----|
| **Chaff** (torchhound) | Original inspiration — Python search noise generator. Simple but effective concept; random queries are too easy to filter. | [github.com/torchhound/Chaff](https://github.com/torchhound/Chaff) |
| **Noisy** (1tayH) | Most popular traffic noise generator (~2k stars). Crawls random URLs with realistic timing. Docker forks (madereddy/noisy) added async + CrUX top-site lists. | [github.com/1tayH/noisy](https://github.com/1tayH/noisy) |
| **ISP Data Pollution** (essandess) | Headless browser approach for realistic browsing sessions. EFF critique highlighted that ISPs can baseline-filter uniform noise. | [github.com/essandess/isp-data-pollution](https://github.com/essandess/isp-data-pollution) |
| **TrackMeNot** (Nissenbaum & Howe, NYU) | Academic browser extension — pioneered *evolving* fake search queries that follow logical progressions. Key insight: query coherence matters. | [trackmenot.io](https://www.trackmenot.io) |
| **AdNauseam** (Howe et al.) | Built on uBlock Origin — silently clicks every blocked ad to poison ad profiles. Actively maintained (~6.2k stars). Banned from Chrome Web Store by Google. | [adnauseam.io](https://adnauseam.io) |
| **Noiszy** | Browser extension that visits user-approved sites in the background. Simple concept, limited scope. | [noiszy.com](https://noiszy.com) |
| **Location Guard** (Chatziko, Ecole Polytechnique) | Adds Laplace noise to geolocation API — provides provable differential privacy guarantees. Formal privacy model is the gold standard. | [github.com/chatziko/location-guard](https://github.com/chatziko/location-guard) |
| **Make Internet Noise** | Web-based — opens random Google "I'm Feeling Lucky" searches. Created in 2017 in response to US ISP privacy rule rollback. | [makeinternetnoise.com](http://makeinternetnoise.com) |
| **Facebook Purge** (stardothosting) | Edit-poison-delete cycle for Facebook data. Novel approach: poison backups before deletion. | [github.com/stardothosting/facebook-purge](https://github.com/stardothosting/facebook-purge) |

**Key insight from prior art:** No existing tool combines persona-coherent search noise with realistic browsing follow-through and proper timing models. The existing tools are all "spray random requests" — effective in 2017, trivially filterable now.

**Academic references:**
- Howe & Nissenbaum, "TrackMeNot: Resisting Surveillance in Web Search" (2009)
- Roca et al., "FPRandom: Randomizing core browser objects to break advanced device fingerprinting techniques" (ESSoS 2017)
- EFF, "Limitations of ISP Data Pollution Tools" (2017) — [eff.org/deeplinks/2017/05/limitations-isp-data-pollution-tools](https://www.eff.org/deeplinks/2017/05/limitations-isp-data-pollution-tools)

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Async runtime | asyncio |
| HTTP client | aiohttp |
| Browser automation | Playwright (async API) |
| CLI framework | Click |
| Configuration | TOML (tomllib stdlib + tomli-w for writing) |
| Local state | SQLite (aiosqlite) |
| Daemon (macOS) | launchd plist generation |
| Daemon (Linux) | systemd unit generation |
| Testing | pytest + pytest-asyncio |
| Packaging | pip / pipx installable |
