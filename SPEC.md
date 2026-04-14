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
  - [Fingerprint Profiles](#fingerprint-profiles)
- [Configuration](#configuration)
- [Multi-Machine Sync](#multi-machine-sync)
- [CLI Interface](#cli-interface)
- [Privacy & Ethics](#privacy--ethics)
- [Inspiration & Prior Art](#inspiration--prior-art)
- [Data Models](#data-models)
- [Error Handling](#error-handling)
- [Daemon Lifecycle](#daemon-lifecycle)
- [Logging & Observability](#logging--observability)
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
- **Full anti-fingerprinting** — We don't try to make your real browser untrackable (that's Tor/Brave territory). We *do* give each persona a distinct, realistic fingerprint so noise traffic looks like multiple people. See [Fingerprint Profiles](#fingerprint-profiles).
- **Data scraping** — Search results are parsed for persona evolution only, never stored or transmitted.
- **DDoS or abuse** — Rate limits are enforced. Traffic volume is modest by design.

## Architecture

```
+-----------+-------------------------+-------------+
|                 CLI / Daemon                      |
|            (Click + launchd plist)                |
+-----------+-------------------------+-------------+
|                  Scheduler                        |
|       (Poisson timing + circadian model)          |
+-----------+-------------------------+-------------+
|  Persona  |     Transport Layer     |   Plugin    |
|  Engine   |  +---------+---------+  |   Registry  |
|           |  |  HTTP   | Browser |  |             |
|           |  |(aiohttp)|(Playwrt)|  |             |
|           |  +---------+---------+  |             |
+-----------+-------------------------+-------------+
|           Config (shared / local)                 |
|      ~/.config/murmurate/ or custom               |
+-----------+-------------------------+-------------+
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
- Topic trees are **append-only** — branches only grow, never prune. This makes multi-machine sync safe (see [Multi-Machine Sync](#multi-machine-sync))
- Trees are **non-deterministic** across machines — each machine's sessions produce different search results and therefore different branches. This is desirable: more machines = more diverse noise

**Topic evolution algorithm:**
- Each `TopicNode` has: `topic` (string), `depth` (int), `children` (list of TopicNode), `query_count` (int), `last_used` (ISO timestamp)
- When a session runs on a topic, the transport returns page content (titles, headings, link text, "related searches" / "People also ask" snippets)
- **Keyword extraction** (TF-IDF via scikit-learn's `TfidfVectorizer`): extract top-N candidate subtopics from the returned content, filtered against the parent topic for relevance
- **Drift parameter** (`drift_rate`, 0.0-1.0): controls the probability of accepting a candidate subtopic that is only loosely related to the parent. At 0.0, only highly relevant subtopics are added. At 1.0, the persona wanders freely.
- **Depth limit** (`max_tree_depth`): prevents runaway branching. Default: 5 levels deep from the seed.
- **Branch selection for sessions**: weighted random — prefers less-visited branches (`query_count`) and shallower nodes (to build breadth before depth), with a configurable bias toward leaf nodes (to deepen existing threads)

**Session generation:**
- The Persona Engine (not the plugin) generates the query sequence for a session. It selects a topic branch, then builds a sequence of 3-8 queries that simulate a logical research progression:
  1. Start with a broad query at the branch's depth level
  2. Each subsequent query refines or follows up based on the topic tree's structure
  3. Final queries may explore adjacent branches (simulating "while I'm at it..." behavior)
- The plugin receives a `SessionContext` (see [Data Models](#data-models)) containing the full query sequence, persona expertise level, and prior session history — it handles site-specific URL construction and navigation
- Sessions have realistic dwell patterns: search → click result → read (30-120s) → refine query → click another result → done
- Some sessions are shallow (quick lookup), some are deep dives (20+ minutes across multiple sites)

**Evolution over time:**
- After each session, new subtopics extracted from results are appended to the topic tree
- Personas develop "expertise" — early queries are broad ("woodworking for beginners"), later ones are specific ("mortise gauge setup for through tenons"). The `query_count` and `depth` on each node drive this progression.
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
- Rotates User-Agent strings from a bundled pool (curated list of real browser UAs, updated with each Murmurate release — no runtime network fetches for privacy)
- Follows redirects, parses HTML responses to extract links for "click-through"
- Cannot execute JavaScript — sites that require JS get escalated to BrowserTransport
- Good for: search queries, Wikipedia, Reddit, news sites, Amazon product browsing

**BrowserTransport (Playwright async):**
- Full Chromium engine, indistinguishable from real browsing
- Handles JS-heavy sites, SPAs, infinite scroll
- Simulates human behavior: mouse movements, scroll patterns, realistic typing speed with typos/corrections
- Resource-heavy — used for ~30% of sessions by default, configurable
- Browser instance pooling: maintains up to `browser_pool_size` concurrent browser contexts. Contexts rotate after 20 sessions or 2 hours (whichever comes first) to avoid fingerprint staleness. When all pool slots are busy, new browser sessions queue until a slot frees (with a configurable timeout, default 60s, after which the session falls back to HTTP or is skipped). Each rotation creates a fresh profile (no persistent cookies across rotations).
- Good for: YouTube (watch partial videos), Google with JS, sites with bot detection
- **TLS fingerprint note:** aiohttp and Playwright have different TLS fingerprints (cipher suites, extensions, ALPN). A sophisticated network observer could distinguish HTTP-transport sessions from browser-transport sessions by TLS characteristics alone. This is an accepted limitation — the two transports are meant to simulate different "applications" a user might use (API client vs. browser), and the per-domain consistency (same transport type for the same site) reduces this as a correlation vector.

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

    async def execute_search(self, context: SessionContext, transport: Transport) -> list[SearchResult]
    async def browse_result(self, result: SearchResult, context: SessionContext, transport: Transport) -> BrowseAction
```

Query sequence generation is handled by the Persona Engine (not the plugin). The plugin receives a `SessionContext` containing the pre-built query sequence, persona expertise level, and prior queries — it handles site-specific URL construction and navigation. See [Data Models](#data-models) for the full `SessionContext` definition.

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

### Fingerprint Profiles

Each persona gets a unique, consistent browser fingerprint — so noise traffic from one machine looks like multiple distinct people sharing the same connection (e.g., a household).

**Why this matters:** Without fingerprint variation, all Playwright sessions share the same canvas hash, WebGL renderer, screen resolution, and font list. An observer correlating traffic with fingerprints would see one person doing a suspicious volume of diverse research. With per-persona profiles, they see a household of 3-5 people with normal browsing patterns.

**What we fuzz (per persona):**

| Vector | How | Source |
|--------|-----|--------|
| Screen resolution + viewport | Playwright context `viewport` + `screen` | Bundled distribution data from real browser populations |
| Timezone + locale | Playwright context `timezoneId` + `locale` | Sampled from common timezone/locale pairs |
| User-Agent | Aligned with platform choice | Bundled UA pool, consistent with other fingerprint vectors |
| Platform | macOS / Windows / Linux | Weighted random (Windows ~72%, macOS ~16%, Linux ~4%, mobile ~8%) matching real-world share |
| `navigator.hardwareConcurrency` | Playwright `extra_http_headers` + JS injection | Common values: 4, 8, 12, 16 |
| `navigator.deviceMemory` | JS injection via `addInitScript` | Common values: 4, 8, 16 |
| WebGL renderer + vendor | JS override via `addInitScript` | Bundled list of real GPU strings per platform |
| Canvas noise | Small pixel perturbation via `addInitScript` | Deterministic per-persona seed — same persona always produces the same canvas hash |
| Installed fonts | CSS injection to mask/expose font subsets | Platform-appropriate font lists (don't give a "Linux persona" Helvetica Neue) |
| Language + Accept-Language header | Playwright context `locale` + `extra_http_headers` | Consistent with timezone (don't pair `Asia/Tokyo` with `en-US`) |

**What we do NOT fuzz:**
- Audio fingerprint — diminishing returns, complex to spoof reliably
- WebRTC local IP — VPN territory, not our scope
- Battery API — deprecated in most browsers
- Full anti-bot evasion (Cloudflare Turnstile, DataDome) — arms race, not our fight

**Profile generation:**
- When a persona is created, a `FingerprintProfile` is generated by sampling from bundled distribution data
- The profile is stored in the persona JSON file and remains consistent across all sessions for that persona (a "person" doesn't change their screen resolution every day)
- Profiles are internally consistent — platform, UA, fonts, WebGL renderer, and timezone all align. A Windows persona gets DirectX-style WebGL strings and Windows fonts, not Metal renderers and San Francisco.
- Distribution data is bundled with Murmurate (sourced from public browser stats and EFF's Cover Your Tracks dataset). No runtime fetches.

**Transport integration:**
- **BrowserTransport**: applies the full fingerprint profile to each Playwright browser context via context options + `addInitScript` for JS-level overrides
- **HttpTransport**: applies the persona's User-Agent, Accept-Language, and platform-consistent headers. No canvas/WebGL/font fuzzing (not applicable to raw HTTP).

**Consistency model:**
- Same persona = same fingerprint, always. This is critical — a "person" who changes fingerprint every session is more suspicious than one with a static fingerprint.
- Fingerprint profiles sync across machines with the rest of the persona state. All machines running the "woodworker" persona present the same fingerprint.
- Profile rotation: if a persona has been active for >90 days, the profile can optionally "upgrade" (simulating a browser or OS update) — new UA version, possibly new screen resolution. This is configurable and off by default.

## Configuration

All configuration lives in a single `config.toml` file within the config directory.

```toml
# Config and persona files include a version field for forward compatibility.
# Unknown fields are silently ignored (allows newer configs to be read by older versions).
# Breaking schema changes increment the major version; Murmurate refuses to load
# configs with a higher major version than it supports and prints an upgrade message.
config_version = 1

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
- Persona topic trees are **append-only** — branches only grow, never prune or modify existing nodes. On file sync, if two machines added different branches to the same parent node, both survive (set-union merge). The `query_count` and `last_used` fields use max-wins. In practice, cloud sync (iCloud, Syncthing) handles this via last-write-wins on the JSON file, and since the trees are append-only, the "losing" machine's additions simply appear on the next session when that machine reads the synced file
- Each machine stamps session log entries with a machine ID (hostname by default, configurable) for audit

## CLI Interface

**`run` vs `start`:** `run` fires N sessions with realistic Poisson timing but exits after all sessions complete. `start` runs the daemon indefinitely until stopped. Both respect the scheduler's timing model — `run` is not "fire N sessions immediately."

```bash
# On-demand session (fires 10 sessions with realistic timing, then exits)
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

# Add a new persona with topic seeds
murmurate personas add gardener --seeds "container gardening" --seeds "herb growing"

# Show session history
murmurate history --last 24h

# Traffic stats and self-assessment
murmurate stats
murmurate stats --days 30

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
- `robots.txt` handling: **ignored by default** (matching real browser behavior — real users never check robots.txt). Optional `respect_robots_txt = true` in config for users who prefer the ethical-crawler default. Note: respecting robots.txt can actually *reduce* realism and make traffic identifiable, since real browsers visit disallowed paths freely.
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
| **Cover Your Tracks** (EFF) | Browser fingerprinting test suite — source for realistic fingerprint distribution data used to generate per-persona profiles. Successor to Panopticlick. | [coveryourtracks.eff.org](https://coveryourtracks.eff.org) |

**Key insight from prior art:** No existing tool combines persona-coherent search noise with realistic browsing follow-through and proper timing models. The existing tools are all "spray random requests" — effective in 2017, trivially filterable now.

**Academic references:**
- Howe & Nissenbaum, "TrackMeNot: Resisting Surveillance in Web Search" (2009)
- Roca et al., "FPRandom: Randomizing core browser objects to break advanced device fingerprinting techniques" (ESSoS 2017)
- EFF, "Limitations of ISP Data Pollution Tools" (2017) — [eff.org/deeplinks/2017/05/limitations-isp-data-pollution-tools](https://www.eff.org/deeplinks/2017/05/limitations-isp-data-pollution-tools)

## Data Models

### Core Types

```python
@dataclass
class TopicNode:
    topic: str                    # e.g., "hand planes"
    depth: int                    # 0 = seed, 1 = first-level subtopic, etc.
    children: list[TopicNode]     # subtopics discovered from search results
    query_count: int              # how many times this node has been used in a session
    last_used: str | None         # ISO 8601 timestamp, or None if never used

@dataclass
class FingerprintProfile:
    platform: str                 # "windows", "macos", "linux", "android", "ios"
    user_agent: str               # full UA string, consistent with platform
    screen_width: int             # e.g., 1920
    screen_height: int            # e.g., 1080
    viewport_width: int           # e.g., 1536 (accounts for taskbar/dock)
    viewport_height: int          # e.g., 864
    timezone_id: str              # e.g., "America/Chicago"
    locale: str                   # e.g., "en-US"
    accept_language: str          # e.g., "en-US,en;q=0.9"
    hardware_concurrency: int     # e.g., 8
    device_memory: int            # e.g., 8 (GB)
    webgl_vendor: str             # e.g., "Google Inc. (NVIDIA)"
    webgl_renderer: str           # e.g., "ANGLE (NVIDIA GeForce GTX 1060)"
    canvas_noise_seed: int        # deterministic seed for pixel perturbation
    fonts: list[str]              # platform-appropriate font list subset
    created_at: str               # ISO 8601
    last_rotated: str | None      # ISO 8601, if profile was "upgraded"

@dataclass
class PersonaState:
    name: str                     # e.g., "woodworker"
    version: int                  # schema version for forward compatibility
    seeds: list[str]              # original seed interests
    topic_tree: list[TopicNode]   # root nodes (one per seed)
    fingerprint: FingerprintProfile  # consistent browser fingerprint for this persona
    created_at: str               # ISO 8601
    total_sessions: int
    expertise_level: float        # 0.0 (beginner) to 1.0 (expert), derived from total_sessions and tree depth

@dataclass
class SessionContext:
    persona: PersonaState
    queries: list[str]            # pre-built query sequence (3-8 queries)
    current_query_index: int
    topic_branch: TopicNode       # the branch being explored
    expertise_level: float        # persona's current expertise (affects query specificity)
    prior_results: list[str]      # titles/snippets from earlier queries in this session
    session_id: str               # UUID for logging

@dataclass
class BrowsingSession:
    session_id: str               # UUID
    persona_name: str
    plugin_name: str              # which site plugin handles this session
    context: SessionContext
    transport_type: TransportType # HTTP or BROWSER
    estimated_duration_s: int
    scheduled_at: str             # ISO 8601

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str                  # description text from the search result
    position: int                 # rank on the results page

@dataclass
class BrowseAction:
    url_visited: str
    dwell_time_s: float           # how long the transport "read" the page
    links_found: list[str]        # outbound links (for potential follow-through)
    content_snippets: list[str]   # extracted text for topic evolution (titles, headings, related terms)
    status_code: int

@dataclass
class SessionResult:
    session_id: str
    persona_name: str
    plugin_name: str
    transport_type: TransportType
    queries_executed: int
    results_browsed: int
    total_duration_s: float
    new_subtopics: list[str]      # topics extracted for tree evolution
    errors: list[str]             # any non-fatal errors encountered
    completed_at: str             # ISO 8601
    machine_id: str

class TransportType(Enum):
    HTTP = "http"
    BROWSER = "browser"
    EITHER = "either"
```

### Persona JSON Schema (on disk)

```json
{
  "name": "woodworker",
  "version": 1,
  "seeds": ["woodworking"],
  "created_at": "2026-03-12T10:00:00Z",
  "total_sessions": 47,
  "fingerprint": {
    "platform": "windows",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "screen_width": 1920,
    "screen_height": 1080,
    "viewport_width": 1536,
    "viewport_height": 864,
    "timezone_id": "America/Chicago",
    "locale": "en-US",
    "accept_language": "en-US,en;q=0.9",
    "hardware_concurrency": 8,
    "device_memory": 16,
    "webgl_vendor": "Google Inc. (NVIDIA)",
    "webgl_renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0)",
    "canvas_noise_seed": 48291,
    "fonts": ["Arial", "Calibri", "Cambria", "Consolas", "Courier New", "Georgia", "Segoe UI", "Tahoma", "Times New Roman", "Verdana"],
    "created_at": "2026-03-12T10:00:00Z",
    "last_rotated": null
  },
  "topic_tree": [
    {
      "topic": "woodworking",
      "depth": 0,
      "query_count": 12,
      "last_used": "2026-03-12T14:30:00Z",
      "children": [
        {
          "topic": "hand planes",
          "depth": 1,
          "query_count": 5,
          "last_used": "2026-03-11T20:15:00Z",
          "children": [
            {
              "topic": "Stanley No. 4 restoration",
              "depth": 2,
              "query_count": 2,
              "last_used": "2026-03-10T09:45:00Z",
              "children": []
            }
          ]
        }
      ]
    }
  ]
}
```

### SQLite State Database Schema (`local/state.db`)

```sql
-- Session history (powers `murmurate history` and stats)
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,           -- UUID
    persona_name TEXT NOT NULL,
    plugin_name TEXT NOT NULL,
    transport_type TEXT NOT NULL,   -- 'http' or 'browser'
    queries_executed INTEGER,
    results_browsed INTEGER,
    duration_s REAL,
    machine_id TEXT NOT NULL,
    started_at TEXT NOT NULL,       -- ISO 8601
    completed_at TEXT,
    status TEXT DEFAULT 'running'   -- 'running', 'completed', 'failed', 'cancelled'
);

-- Per-domain rate limit tracking (sliding window)
CREATE TABLE rate_limits (
    domain TEXT NOT NULL,
    request_time TEXT NOT NULL,     -- ISO 8601
    PRIMARY KEY (domain, request_time)
);

-- Index for efficient window queries
CREATE INDEX idx_rate_limits_domain_time ON rate_limits (domain, request_time);

-- Periodic cleanup: DELETE FROM rate_limits WHERE request_time < datetime('now', '-1 hour');
```

## Error Handling

**Transport failures:**
- HTTP errors (429, 503, timeout): exponential backoff with jitter, max 3 retries per request. After 3 failures, skip that query in the session and log it.
- If HTTP gets a bot challenge (CAPTCHA page detected via heuristic — e.g., page contains "verify you are human" patterns), escalate to BrowserTransport for that domain for the rest of the session.
- Playwright crash (browser process dies): log the error, discard the session, remove the crashed context from the pool, and create a fresh one. Do not retry the session — the scheduler will generate new sessions naturally.
- DNS resolution failure: skip the domain, log it, continue with other sessions. After 5 consecutive DNS failures across any domain, pause all sessions for 60s and check connectivity.

**Plugin exceptions:**
- Plugins run in a try/except wrapper. An unhandled exception in a plugin kills that session only — logged with full traceback. The plugin remains available for future sessions.
- If a plugin fails 5 consecutive sessions, it is temporarily disabled for 1 hour with a warning log. After the cooldown, it is re-enabled automatically.

**Database errors:**
- SQLite locked (e.g., another process accessing the file): retry with backoff up to 3 times. If still locked, skip logging for that session and continue — session execution is not blocked by logging failures.
- Schema migration failures on startup: refuse to start, print error and migration instructions.

**Graceful degradation:**
- If Playwright is not installed (`playwright` import fails), run in HTTP-only mode with a startup warning. All plugins with `preferred_transport = BROWSER` fall back to HTTP where possible, or are disabled.
- If the config directory is missing or unreadable, refuse to start with a clear error message pointing to setup instructions.
- If persona files are corrupted (invalid JSON), skip that persona, log a warning, and continue with remaining personas. If all personas are corrupted, fall back to auto-generated personas.

## Daemon Lifecycle

**Daemonization:**
- Murmurate does **not** self-daemonize (no double-fork). On macOS, use the generated launchd plist (`murmurate install-daemon`). On Linux, use the generated systemd unit (`murmurate install-daemon --systemd`).
- `murmurate start` runs the process in the foreground (suitable for launchd/systemd management). It writes `local/daemon.pid` on startup.
- `murmurate start --background` is a convenience wrapper that launches the process in the background via `nohup` and writes the PID file. This is the fallback for systems without launchd/systemd.

**PID file management:**
- On startup: check if `local/daemon.pid` exists. If it does, check if the PID is still running (`os.kill(pid, 0)`). If running, refuse to start ("already running, use `murmurate stop` first"). If stale (process gone), remove the PID file and proceed.
- On clean shutdown: remove the PID file.

**Signal handling:**
- `SIGTERM`: graceful shutdown — stop scheduling new sessions, wait up to 30s for in-flight sessions to complete, then exit. This is what `murmurate stop` sends.
- `SIGINT` (Ctrl+C): immediate shutdown — cancel in-flight sessions, close browser contexts, exit.
- `SIGHUP`: reload `config.toml` and persona files without restarting. Log what changed.

**`murmurate stop`:**
- Reads PID from `local/daemon.pid`, sends `SIGTERM`, waits up to 30s for exit. If still running after 30s, sends `SIGKILL` and warns.

## Logging & Observability

**Log location:** `{config_dir}/local/murmurate.log`

**Log format:** Structured JSON lines (one JSON object per line) for machine parsing, with a human-readable `--log-format text` option.

```json
{"ts": "2026-03-12T14:30:00Z", "level": "INFO", "event": "session_complete", "session_id": "abc-123", "persona": "woodworker", "plugin": "google", "transport": "http", "queries": 5, "duration_s": 127.3, "machine_id": "wiles"}
```

**Log levels:** DEBUG, INFO, WARNING, ERROR
- INFO: session start/complete, daemon start/stop, persona evolution events
- WARNING: rate limit hits, plugin temporary failures, stale PID detected
- ERROR: transport crashes, plugin disabled, database errors
- DEBUG: individual query execution, timing calculations, topic tree mutations

**Log rotation:** Managed by the OS (logrotate on Linux, newsyslog on macOS via the generated plist). Murmurate does not rotate its own logs — it writes to the file and trusts the system to manage it. The `install-daemon` command configures rotation as part of setup.

**`murmurate status` output:**
```
Murmurate v0.1.0 — running (PID 12345, since 2026-03-12 07:00)
Machine: wiles
Config: ~/Library/Mobile Documents/com~apple~CloudDocs/murmurate/

Sessions today: 34 (18 HTTP, 16 browser)
Active sessions: 2
Next scheduled: 14:37 (persona: woodworker, plugin: amazon)

Personas: 5 active (woodworker: 47 sessions, amateur-chef: 31, ...)
Plugins: 6 enabled (google, duckduckgo, youtube, amazon, reddit, wikipedia)
Browser pool: 1/2 contexts in use
```

**`murmurate stats` output (self-assessment):**
```
Traffic distribution (last 7 days):
  Sessions: 156 total (avg 22.3/day)
  Timing: mean gap 14.2min, stddev 8.7min (Poisson λ=4.2/hr)
  Peak hours: 10:15, 20:30 (configured: 10:00, 20:00)
  Transport split: 68% HTTP, 32% browser (configured: 70/30)
  Plugin distribution: google 28%, youtube 19%, amazon 18%, reddit 15%, ...
  Topic diversity: 23 unique branches explored, 4 new subtopics added
  Errors: 3 (2x rate limit, 1x DNS timeout)
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Async runtime | asyncio |
| HTTP client | aiohttp |
| Browser automation | Playwright (async API) |
| CLI framework | Click |
| Configuration | TOML (tomllib stdlib + tomli-w for writing) |
| Topic extraction | scikit-learn (TfidfVectorizer) |
| Local state | SQLite (aiosqlite) |
| Daemon (macOS) | launchd plist generation |
| Daemon (Linux) | systemd unit generation |
| Testing | pytest + pytest-asyncio |
| Packaging | pip / pipx installable |
