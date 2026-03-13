# Murmurate Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a privacy tool that generates realistic decoy internet activity using persona-driven browsing sessions with human-like timing.

**Architecture:** Single async Python process with clean internal boundaries — persona engine generates coherent query sequences, two transport implementations (aiohttp + Playwright) execute them, site plugins handle per-site navigation, and a Poisson/circadian scheduler orchestrates timing. Config syncs across machines; local state stays local.

**Tech Stack:** Python 3.12+, asyncio, aiohttp, Playwright, Click, TOML, scikit-learn (TF-IDF), SQLite (aiosqlite), pytest

---

## File Structure

```
murmurate/
├── pyproject.toml
├── src/
│   └── murmurate/
│       ├── __init__.py              # version string
│       ├── __main__.py              # python -m murmurate entry
│       ├── cli.py                   # Click CLI commands
│       ├── config.py                # Config loading, defaults, validation
│       ├── models.py                # All dataclasses + enums
│       ├── database.py              # SQLite state (sessions, rate limits)
│       ├── log.py                   # Structured JSON logging setup
│       ├── persona/
│       │   ├── __init__.py
│       │   ├── engine.py            # Session generation, branch selection
│       │   ├── evolution.py         # TF-IDF topic extraction + tree growth
│       │   ├── fingerprint.py       # FingerprintProfile generation
│       │   ├── topics.py            # Built-in topic pool loader
│       │   └── storage.py           # Persona JSON read/write
│       ├── transport/
│       │   ├── __init__.py
│       │   ├── base.py              # Abstract Transport interface
│       │   ├── http.py              # HttpTransport (aiohttp)
│       │   ├── browser.py           # BrowserTransport (Playwright)
│       │   └── pool.py              # Browser context pool management
│       ├── plugins/
│       │   ├── __init__.py
│       │   ├── base.py              # SitePlugin ABC
│       │   ├── registry.py          # Plugin discovery + management
│       │   ├── duckduckgo.py        # HTTP-friendly, good first plugin
│       │   ├── wikipedia.py         # Pure HTTP, lightweight
│       │   ├── google.py            # Web search, JS optional
│       │   ├── youtube.py           # Browser-required
│       │   ├── amazon.py            # Product browsing
│       │   ├── reddit.py            # Subreddit browsing
│       │   └── bing.py              # Web search
│       ├── scheduler/
│       │   ├── __init__.py
│       │   ├── scheduler.py         # Main scheduling loop
│       │   ├── timing.py            # Poisson + circadian model
│       │   └── rate_limiter.py      # Per-domain rate limiting
│       └── daemon/
│           ├── __init__.py
│           ├── lifecycle.py          # PID, signals, start/stop
│           └── install.py            # launchd plist / systemd unit gen
├── data/
│   ├── user_agents.json             # Bundled UA pool
│   ├── fingerprints/
│   │   ├── platforms.json           # Platform distribution weights
│   │   ├── screens.json             # Screen resolutions per platform
│   │   ├── webgl.json               # WebGL strings per platform
│   │   └── fonts.json               # Font lists per platform
│   └── topic_pools/
│       ├── hobbies.json
│       ├── academic.json
│       ├── shopping.json
│       ├── travel.json
│       └── professional.json
└── tests/
    ├── conftest.py                   # Shared fixtures
    ├── test_models.py
    ├── test_config.py
    ├── test_database.py
    ├── test_persona_engine.py
    ├── test_persona_evolution.py
    ├── test_persona_storage.py
    ├── test_fingerprint.py
    ├── test_transport_http.py
    ├── test_transport_browser.py
    ├── test_transport_pool.py
    ├── test_plugin_base.py
    ├── test_plugin_registry.py
    ├── test_plugin_duckduckgo.py
    ├── test_plugin_wikipedia.py
    ├── test_plugin_google.py
    ├── test_plugin_youtube.py
    ├── test_plugin_amazon.py
    ├── test_plugin_reddit.py
    ├── test_plugin_bing.py
    ├── test_scheduler.py
    ├── test_timing.py
    ├── test_rate_limiter.py
    ├── test_cli.py
    └── test_daemon.py
```

---

## Chunk 1: Foundation (Models, Config, Database, Logging)

Everything else depends on these. After this chunk you can load config, persist state, and log — but nothing runs yet.

### Task 1: Project scaffolding + models

**Files:**
- Create: `pyproject.toml`
- Create: `src/murmurate/__init__.py`
- Create: `src/murmurate/models.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "murmurate"
version = "0.1.0"
description = "Privacy tool that generates realistic decoy internet activity"
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
dependencies = [
    "aiohttp>=3.9",
    "aiosqlite>=0.20",
    "click>=8.1",
    "tomli-w>=1.0",
    "scikit-learn>=1.4",
]

[project.optional-dependencies]
browser = ["playwright>=1.40"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "aioresponses>=0.7",
]

[project.scripts]
murmurate = "murmurate.cli:cli"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Write `src/murmurate/__init__.py`**

```python
"""Murmurate — realistic decoy internet activity generator."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Write failing tests for all data models**

```python
# tests/test_models.py
from murmurate.models import (
    TopicNode, FingerprintProfile, PersonaState, SessionContext,
    BrowsingSession, SearchResult, BrowseAction, SessionResult,
    TransportType,
)

def test_topic_node_creation():
    node = TopicNode(topic="woodworking", depth=0, children=[], query_count=0, last_used=None)
    assert node.topic == "woodworking"
    assert node.depth == 0
    assert node.children == []

def test_topic_node_add_child():
    parent = TopicNode(topic="woodworking", depth=0, children=[], query_count=0, last_used=None)
    child = TopicNode(topic="hand planes", depth=1, children=[], query_count=0, last_used=None)
    parent.children.append(child)
    assert len(parent.children) == 1
    assert parent.children[0].topic == "hand planes"

def test_fingerprint_profile_creation():
    fp = FingerprintProfile(
        platform="windows", user_agent="Mozilla/5.0", screen_width=1920,
        screen_height=1080, viewport_width=1536, viewport_height=864,
        timezone_id="America/Chicago", locale="en-US",
        accept_language="en-US,en;q=0.9", hardware_concurrency=8,
        device_memory=16, webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer="ANGLE (NVIDIA GeForce GTX 1660)",
        canvas_noise_seed=48291,
        fonts=["Arial", "Calibri", "Consolas"],
        created_at="2026-03-12T10:00:00Z", last_rotated=None,
    )
    assert fp.platform == "windows"
    assert fp.canvas_noise_seed == 48291

def test_persona_state_creation():
    fp = FingerprintProfile(
        platform="macos", user_agent="Mozilla/5.0", screen_width=2560,
        screen_height=1440, viewport_width=2560, viewport_height=1340,
        timezone_id="America/New_York", locale="en-US",
        accept_language="en-US,en;q=0.9", hardware_concurrency=10,
        device_memory=16, webgl_vendor="Apple",
        webgl_renderer="Apple M1 Pro", canvas_noise_seed=99999,
        fonts=["Helvetica Neue", "SF Pro"], created_at="2026-03-12T10:00:00Z",
        last_rotated=None,
    )
    tree = [TopicNode(topic="cooking", depth=0, children=[], query_count=0, last_used=None)]
    persona = PersonaState(
        name="chef", version=1, seeds=["cooking"], topic_tree=tree,
        fingerprint=fp, created_at="2026-03-12T10:00:00Z",
        total_sessions=0, expertise_level=0.0,
    )
    assert persona.name == "chef"
    assert persona.fingerprint.platform == "macos"

def test_transport_type_enum():
    assert TransportType.HTTP.value == "http"
    assert TransportType.BROWSER.value == "browser"
    assert TransportType.EITHER.value == "either"

def test_search_result_creation():
    result = SearchResult(title="Test", url="https://example.com", snippet="A test", position=1)
    assert result.position == 1

def test_session_result_creation():
    result = SessionResult(
        session_id="abc-123", persona_name="woodworker", plugin_name="google",
        transport_type=TransportType.HTTP, queries_executed=5, results_browsed=3,
        total_duration_s=127.3, new_subtopics=["hand planes"],
        errors=[], completed_at="2026-03-12T14:30:00Z", machine_id="roguenode",
    )
    assert result.queries_executed == 5
    assert result.new_subtopics == ["hand planes"]
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd murmurate && pip install -e ".[dev]" && pytest tests/test_models.py -v`
Expected: FAIL (murmurate.models not found)

- [ ] **Step 5: Write `src/murmurate/models.py`**

Implement all dataclasses and enums exactly as defined in the spec's Data Models section. Use `@dataclass` from `dataclasses`. `TransportType` is an `Enum`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "feat: project scaffolding + data models"
```

---

### Task 2: Config loading

**Files:**
- Create: `src/murmurate/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for config**

```python
# tests/test_config.py
import tempfile
from pathlib import Path
from murmurate.config import load_config, MurmurateConfig, DEFAULT_CONFIG

def test_default_config_loads():
    config = MurmurateConfig()
    assert config.scheduler.sessions_per_hour_min == 3
    assert config.scheduler.sessions_per_hour_max == 8
    assert config.transport.browser_ratio == 0.3
    assert config.config_version == 1

def test_load_config_from_toml(tmp_path):
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('''
config_version = 1

[scheduler]
sessions_per_hour = { min = 5, max = 10 }
active_hours = { start = "08:00", end = "22:00", timezone = "America/Chicago" }
peak_hours = ["11:00", "21:00"]
quiet_hours = { start = "22:30", end = "07:30" }
burst_probability = 0.2

[rate_limits]
global_bandwidth_mbps = 10
default_per_domain_rpm = 15

[transport]
browser_ratio = 0.5
browser_pool_size = 3
headless = true
''')
    config = load_config(tmp_path)
    assert config.scheduler.sessions_per_hour_min == 5
    assert config.transport.browser_ratio == 0.5
    assert config.rate_limits.global_bandwidth_mbps == 10

def test_load_config_missing_file_uses_defaults(tmp_path):
    config = load_config(tmp_path)
    assert config.scheduler.sessions_per_hour_min == 3

def test_config_version_too_high_raises(tmp_path):
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('config_version = 999\n')
    import pytest
    with pytest.raises(ValueError, match="config version"):
        load_config(tmp_path)

def test_resolve_config_dir_from_env(tmp_path, monkeypatch):
    from murmurate.config import resolve_config_dir
    monkeypatch.setenv("MURMURATE_CONFIG", str(tmp_path))
    assert resolve_config_dir(None) == tmp_path

def test_resolve_config_dir_cli_flag_takes_precedence(tmp_path, monkeypatch):
    from murmurate.config import resolve_config_dir
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("MURMURATE_CONFIG", str(tmp_path))
    assert resolve_config_dir(other) == other

def test_unknown_fields_ignored(tmp_path):
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('''
config_version = 1
some_future_field = "hello"

[scheduler]
sessions_per_hour = { min = 3, max = 8 }
''')
    config = load_config(tmp_path)
    assert config.scheduler.sessions_per_hour_min == 3
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/test_config.py -v`

- [ ] **Step 3: Implement `src/murmurate/config.py`**

Define `MurmurateConfig` as nested dataclasses (`SchedulerConfig`, `RateLimitConfig`, `TransportConfig`, `PersonaConfig`, `PluginConfig`). **TOML mapping**: inline tables like `sessions_per_hour = { min = 3, max = 8 }` flatten to `sessions_per_hour_min` / `sessions_per_hour_max` attributes; similarly `active_hours`, `quiet_hours`, `typing_wpm`. Include `respect_robots_txt: bool = False` in the top-level config. Implement `load_config(config_dir: Path) -> MurmurateConfig` using `tomllib`. Implement `resolve_config_dir(cli_flag: Path | None) -> Path` with the 3-step resolution (CLI flag → env var → `~/.config/murmurate/`). Supported `config_version` is 1; raise `ValueError` if higher. Unknown fields silently ignored.

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_config.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/murmurate/config.py tests/test_config.py
git commit -m "feat: config loading with TOML support and defaults"
```

---

### Task 3: Structured logging

**Files:**
- Create: `src/murmurate/log.py`

- [ ] **Step 1: Implement `src/murmurate/log.py`**

Set up Python `logging` with a custom JSON formatter for structured output. Provide `setup_logging(log_file: Path, level: str = "INFO", json_format: bool = True)`. The JSON formatter outputs one JSON object per line with fields: `ts`, `level`, `event`, `msg`, plus any extra kwargs. Provide a `get_logger(name: str)` convenience function.

- [ ] **Step 2: Write a quick smoke test**

```python
# tests/test_log.py (just a smoke test — logging is infrastructure)
import json
import tempfile
from pathlib import Path
from murmurate.log import setup_logging, get_logger

def test_json_log_output(tmp_path):
    log_file = tmp_path / "test.log"
    setup_logging(log_file, level="DEBUG", json_format=True)
    logger = get_logger("test")
    logger.info("session_complete", extra={"persona": "woodworker", "plugin": "google"})
    lines = log_file.read_text().strip().split("\n")
    entry = json.loads(lines[-1])
    assert entry["level"] == "INFO"
    assert entry["persona"] == "woodworker"
```

- [ ] **Step 3: Run test — expect PASS**

Run: `pytest tests/test_log.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/murmurate/log.py tests/test_log.py
git commit -m "feat: structured JSON logging"
```

---

### Task 4: SQLite state database

**Files:**
- Create: `src/murmurate/database.py`
- Create: `tests/test_database.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_database.py
import pytest
from murmurate.database import StateDB
from murmurate.models import TransportType

@pytest.fixture
async def db(tmp_path):
    state_db = StateDB(tmp_path / "state.db")
    await state_db.initialize()
    yield state_db
    await state_db.close()

async def test_initialize_creates_tables(db):
    # Should not raise
    assert db is not None

async def test_log_session(db):
    await db.log_session_start(
        session_id="abc-123", persona_name="woodworker",
        plugin_name="google", transport_type="http", machine_id="roguenode",
    )
    session = await db.get_session("abc-123")
    assert session["status"] == "running"
    assert session["persona_name"] == "woodworker"

async def test_complete_session(db):
    await db.log_session_start(
        session_id="abc-123", persona_name="woodworker",
        plugin_name="google", transport_type="http", machine_id="roguenode",
    )
    await db.log_session_complete(
        session_id="abc-123", queries_executed=5, results_browsed=3,
        duration_s=127.3,
    )
    session = await db.get_session("abc-123")
    assert session["status"] == "completed"
    assert session["queries_executed"] == 5

async def test_rate_limit_check(db):
    domain = "google.com"
    # Record 10 requests
    for _ in range(10):
        await db.record_request(domain)
    count = await db.get_request_count(domain, window_seconds=60)
    assert count == 10

async def test_rate_limit_cleanup(db):
    domain = "google.com"
    await db.record_request(domain)
    # Cleanup old entries (our entry is fresh so it should survive)
    await db.cleanup_rate_limits(max_age_seconds=3600)
    count = await db.get_request_count(domain, window_seconds=3600)
    assert count == 1

async def test_session_history(db):
    for i in range(5):
        await db.log_session_start(
            session_id=f"session-{i}", persona_name="woodworker",
            plugin_name="google", transport_type="http", machine_id="roguenode",
        )
        await db.log_session_complete(
            session_id=f"session-{i}", queries_executed=3, results_browsed=2,
            duration_s=60.0,
        )
    history = await db.get_session_history(limit=3)
    assert len(history) == 3
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/test_database.py -v`

- [ ] **Step 3: Implement `src/murmurate/database.py`**

Class `StateDB` wrapping `aiosqlite`. Methods: `initialize()` (creates tables per spec schema), `log_session_start()`, `log_session_complete()`, `log_session_failed()`, `get_session()`, `get_session_history()`, `record_request()`, `get_request_count()`, `cleanup_rate_limits()`, `close()`. Use the exact schema from the spec. Retry with backoff on `OperationalError` (locked database).

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_database.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/murmurate/database.py tests/test_database.py
git commit -m "feat: SQLite state database for sessions and rate limits"
```

---

## Chunk 2: Persona Engine (Storage, Topics, Fingerprints, Evolution, Sessions)

After this chunk, personas can be created, loaded, evolved, and can generate query sequences — but no network traffic yet.

### Task 5: Persona storage (JSON read/write)

**Files:**
- Create: `src/murmurate/persona/__init__.py`
- Create: `src/murmurate/persona/storage.py`
- Create: `tests/test_persona_storage.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_persona_storage.py
import json
from murmurate.persona.storage import save_persona, load_persona, load_all_personas
from murmurate.models import PersonaState, TopicNode, FingerprintProfile

def _make_fingerprint():
    return FingerprintProfile(
        platform="windows", user_agent="Mozilla/5.0", screen_width=1920,
        screen_height=1080, viewport_width=1536, viewport_height=864,
        timezone_id="America/Chicago", locale="en-US",
        accept_language="en-US,en;q=0.9", hardware_concurrency=8,
        device_memory=16, webgl_vendor="Google Inc.",
        webgl_renderer="ANGLE (NVIDIA)", canvas_noise_seed=12345,
        fonts=["Arial"], created_at="2026-03-12T10:00:00Z", last_rotated=None,
    )

def test_save_and_load_persona(tmp_path):
    persona_dir = tmp_path / "personas"
    persona_dir.mkdir()
    tree = [TopicNode(topic="cooking", depth=0, children=[], query_count=0, last_used=None)]
    persona = PersonaState(
        name="chef", version=1, seeds=["cooking"], topic_tree=tree,
        fingerprint=_make_fingerprint(), created_at="2026-03-12T10:00:00Z",
        total_sessions=0, expertise_level=0.0,
    )
    save_persona(persona, persona_dir)
    loaded = load_persona(persona_dir / "chef.json")
    assert loaded.name == "chef"
    assert loaded.topic_tree[0].topic == "cooking"
    assert loaded.fingerprint.platform == "windows"

def test_load_all_personas(tmp_path):
    persona_dir = tmp_path / "personas"
    persona_dir.mkdir()
    for name in ["chef", "gardener"]:
        tree = [TopicNode(topic=name, depth=0, children=[], query_count=0, last_used=None)]
        persona = PersonaState(
            name=name, version=1, seeds=[name], topic_tree=tree,
            fingerprint=_make_fingerprint(), created_at="2026-03-12T10:00:00Z",
            total_sessions=0, expertise_level=0.0,
        )
        save_persona(persona, persona_dir)
    personas = load_all_personas(persona_dir)
    assert len(personas) == 2
    names = {p.name for p in personas}
    assert names == {"chef", "gardener"}

def test_corrupted_persona_skipped(tmp_path):
    persona_dir = tmp_path / "personas"
    persona_dir.mkdir()
    (persona_dir / "bad.json").write_text("{invalid json")
    tree = [TopicNode(topic="good", depth=0, children=[], query_count=0, last_used=None)]
    good = PersonaState(
        name="good", version=1, seeds=["good"], topic_tree=tree,
        fingerprint=_make_fingerprint(), created_at="2026-03-12T10:00:00Z",
        total_sessions=0, expertise_level=0.0,
    )
    save_persona(good, persona_dir)
    personas = load_all_personas(persona_dir)
    assert len(personas) == 1
    assert personas[0].name == "good"

def test_nested_topic_tree_round_trips(tmp_path):
    persona_dir = tmp_path / "personas"
    persona_dir.mkdir()
    child = TopicNode(topic="hand planes", depth=1, children=[], query_count=3, last_used="2026-03-11T20:00:00Z")
    root = TopicNode(topic="woodworking", depth=0, children=[child], query_count=10, last_used="2026-03-12T14:00:00Z")
    persona = PersonaState(
        name="woodworker", version=1, seeds=["woodworking"], topic_tree=[root],
        fingerprint=_make_fingerprint(), created_at="2026-03-12T10:00:00Z",
        total_sessions=47, expertise_level=0.6,
    )
    save_persona(persona, persona_dir)
    loaded = load_persona(persona_dir / "woodworker.json")
    assert loaded.topic_tree[0].children[0].topic == "hand planes"
    assert loaded.topic_tree[0].children[0].query_count == 3
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/test_persona_storage.py -v`

- [ ] **Step 3: Implement persona storage**

`save_persona(persona, persona_dir)` serializes `PersonaState` to JSON matching the spec's on-disk schema. `load_persona(path)` deserializes back. `load_all_personas(persona_dir)` loads all `.json` files, skipping corrupted ones with a warning log. Handle recursive `TopicNode` serialization/deserialization.

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_persona_storage.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/murmurate/persona/ tests/test_persona_storage.py
git commit -m "feat: persona JSON storage with recursive topic tree serialization"
```

---

### Task 6: Built-in topic pools

**Files:**
- Create: `src/murmurate/persona/topics.py`
- Create: `data/topic_pools/hobbies.json`
- Create: `data/topic_pools/academic.json`
- Create: `data/topic_pools/shopping.json`
- Create: `data/topic_pools/travel.json`
- Create: `data/topic_pools/professional.json`
- Create: `tests/test_topics.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_topics.py
from murmurate.persona.topics import load_topic_pools, get_random_seeds

def test_load_topic_pools():
    pools = load_topic_pools()
    assert "hobbies" in pools
    assert "academic" in pools
    assert len(pools["hobbies"]) > 10

def test_get_random_seeds():
    seeds = get_random_seeds(count=3)
    assert len(seeds) == 3
    assert all(isinstance(s, str) for s in seeds)

def test_get_random_seeds_no_duplicates():
    seeds = get_random_seeds(count=10)
    assert len(seeds) == len(set(seeds))
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Create topic pool JSON files**

Each pool is a JSON array of strings. Curate 30-50 topics per pool. Examples:
- `hobbies.json`: woodworking, sourdough baking, watercolor painting, mountain biking, birdwatching, amateur radio, 3D printing, leatherworking, pottery, rock climbing, etc.
- `academic.json`: quantum computing, behavioral economics, marine biology, Roman history, topology, etc.
- `shopping.json`: espresso machines, running shoes, standing desks, mechanical keyboards, cast iron cookware, etc.
- `travel.json`: Okinawa Japan, Patagonia hiking, Iceland ring road, Portuguese Camino, etc.
- `professional.json`: data engineering, UX research, penetration testing, supply chain management, etc.

- [ ] **Step 4: Implement `topics.py`**

`load_topic_pools()` reads all JSON files from the `data/topic_pools/` directory (using `importlib.resources` for package data). `get_random_seeds(count)` draws unique topics from across all pools with uniform weighting.

- [ ] **Step 5: Run tests — expect PASS**

- [ ] **Step 6: Commit**

```bash
git add src/murmurate/persona/topics.py data/topic_pools/ tests/test_topics.py
git commit -m "feat: built-in topic pools for auto-persona generation"
```

---

### Task 7: Fingerprint profile generation

**Files:**
- Create: `src/murmurate/persona/fingerprint.py`
- Create: `data/fingerprints/platforms.json`
- Create: `data/fingerprints/screens.json`
- Create: `data/fingerprints/webgl.json`
- Create: `data/fingerprints/fonts.json`
- Create: `data/user_agents.json`
- Create: `tests/test_fingerprint.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fingerprint.py
from murmurate.persona.fingerprint import generate_fingerprint
from murmurate.models import FingerprintProfile

def test_generate_fingerprint_returns_profile():
    fp = generate_fingerprint()
    assert isinstance(fp, FingerprintProfile)
    assert fp.platform in ("windows", "macos", "linux", "android", "ios")
    assert fp.screen_width > 0
    assert fp.hardware_concurrency in (2, 4, 6, 8, 12, 16)
    assert fp.device_memory in (2, 4, 8, 16, 32)
    assert len(fp.fonts) > 0

def test_fingerprint_internal_consistency():
    fp = generate_fingerprint()
    # Windows persona should have Windows UA
    if fp.platform == "windows":
        assert "Windows" in fp.user_agent
        assert any(f in fp.fonts for f in ["Segoe UI", "Calibri", "Arial"])
    elif fp.platform == "macos":
        assert "Macintosh" in fp.user_agent

def test_fingerprint_timezone_locale_consistency():
    # Generate many and check none have impossible combos
    for _ in range(20):
        fp = generate_fingerprint()
        # Basic sanity: locale language should be in accept_language
        lang = fp.locale.split("-")[0]
        assert lang in fp.accept_language

def test_fingerprint_deterministic_canvas_seed():
    fp = generate_fingerprint()
    assert isinstance(fp.canvas_noise_seed, int)
    assert 0 <= fp.canvas_noise_seed <= 2**32

def test_two_fingerprints_differ():
    fp1 = generate_fingerprint()
    fp2 = generate_fingerprint()
    # At least some fields should differ (probabilistic but overwhelming)
    differs = (
        fp1.canvas_noise_seed != fp2.canvas_noise_seed
        or fp1.screen_width != fp2.screen_width
        or fp1.user_agent != fp2.user_agent
    )
    assert differs
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Create fingerprint distribution data files**

Curate realistic distribution data:
- `platforms.json`: `{"windows": 0.72, "macos": 0.16, "linux": 0.04, "android": 0.06, "ios": 0.02}`
- `screens.json`: per-platform arrays of `{"width": 1920, "height": 1080, "weight": 0.35}` entries
- `webgl.json`: per-platform arrays of `{"vendor": "...", "renderer": "...", "weight": 0.1}` entries
- `fonts.json`: per-platform arrays of common font names
- `user_agents.json`: per-platform arrays of real UA strings

Source realistic values from public browser statistics and StatCounter data.

- [ ] **Step 4: Implement `fingerprint.py`**

`generate_fingerprint() -> FingerprintProfile`: sample platform from weighted distribution, then sample all other fields conditional on platform (screen, UA, WebGL, fonts, timezone/locale pairs). Ensure internal consistency. Use `secrets.randbelow()` for canvas noise seed.

- [ ] **Step 5: Run tests — expect PASS**

- [ ] **Step 6: Commit**

```bash
git add src/murmurate/persona/fingerprint.py data/fingerprints/ data/user_agents.json tests/test_fingerprint.py
git commit -m "feat: per-persona fingerprint profile generation from distribution data"
```

---

### Task 8: Topic evolution (TF-IDF extraction)

**Files:**
- Create: `src/murmurate/persona/evolution.py`
- Create: `tests/test_persona_evolution.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_persona_evolution.py
from murmurate.persona.evolution import extract_subtopics, evolve_topic_tree
from murmurate.models import TopicNode

def test_extract_subtopics_from_content():
    content_snippets = [
        "Best hand planes for beginners — Stanley No. 4 vs No. 5",
        "How to restore a vintage hand plane — japanning and blade sharpening",
        "Hand plane buying guide: block planes, jack planes, smoothing planes",
    ]
    subtopics = extract_subtopics(
        parent_topic="hand planes",
        content_snippets=content_snippets,
        max_topics=5,
        drift_rate=0.1,
    )
    assert len(subtopics) > 0
    assert len(subtopics) <= 5
    assert all(isinstance(t, str) for t in subtopics)

def test_extract_subtopics_filters_parent():
    content_snippets = ["hand planes are great tools for woodworking"]
    subtopics = extract_subtopics(
        parent_topic="hand planes",
        content_snippets=content_snippets,
        max_topics=5,
        drift_rate=0.0,
    )
    # Should not include the parent topic itself
    assert "hand planes" not in [s.lower() for s in subtopics]

def test_evolve_topic_tree_adds_children():
    root = TopicNode(topic="woodworking", depth=0, children=[], query_count=1, last_used=None)
    new_subtopics = ["hand planes", "wood turning", "joinery"]
    evolve_topic_tree(root, new_subtopics, max_depth=5)
    assert len(root.children) == 3
    assert root.children[0].topic == "hand planes"
    assert root.children[0].depth == 1

def test_evolve_topic_tree_respects_depth_limit():
    # Build a tree 4 levels deep
    node = TopicNode(topic="root", depth=0, children=[], query_count=0, last_used=None)
    current = node
    for i in range(4):
        child = TopicNode(topic=f"level-{i+1}", depth=i+1, children=[], query_count=0, last_used=None)
        current.children.append(child)
        current = child
    # Try to add children at depth 5 (max_depth=5 means depth 0-4 are ok, 5 is the limit)
    evolve_topic_tree(current, ["too-deep"], max_depth=5)
    assert len(current.children) == 0  # Should not add at depth 5

def test_evolve_topic_tree_no_duplicates():
    root = TopicNode(topic="cooking", depth=0, children=[
        TopicNode(topic="pasta", depth=1, children=[], query_count=0, last_used=None),
    ], query_count=1, last_used=None)
    evolve_topic_tree(root, ["pasta", "grilling"], max_depth=5)
    topics = [c.topic for c in root.children]
    assert topics.count("pasta") == 1
    assert "grilling" in topics
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement `evolution.py`**

`extract_subtopics(parent_topic, content_snippets, max_topics, drift_rate)`: use `TfidfVectorizer` on content snippets, extract top terms, filter out the parent topic and common stop words, apply drift_rate as acceptance threshold. Return list of subtopic strings.

`evolve_topic_tree(node, new_subtopics, max_depth)`: append new `TopicNode` children to the given node, skipping duplicates (case-insensitive) and respecting depth limit.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/murmurate/persona/evolution.py tests/test_persona_evolution.py
git commit -m "feat: TF-IDF topic evolution for persona topic trees"
```

---

### Task 9: Persona engine (session generation + branch selection)

**Files:**
- Create: `src/murmurate/persona/engine.py`
- Create: `tests/test_persona_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_persona_engine.py
from murmurate.persona.engine import PersonaEngine
from murmurate.models import PersonaState, TopicNode, FingerprintProfile, SessionContext

def _make_persona():
    fp = FingerprintProfile(
        platform="windows", user_agent="Mozilla/5.0", screen_width=1920,
        screen_height=1080, viewport_width=1536, viewport_height=864,
        timezone_id="America/Chicago", locale="en-US",
        accept_language="en-US,en;q=0.9", hardware_concurrency=8,
        device_memory=16, webgl_vendor="Google Inc.",
        webgl_renderer="ANGLE (NVIDIA)", canvas_noise_seed=12345,
        fonts=["Arial"], created_at="2026-03-12T10:00:00Z", last_rotated=None,
    )
    child = TopicNode(topic="hand planes", depth=1, children=[], query_count=2, last_used=None)
    root = TopicNode(topic="woodworking", depth=0, children=[child], query_count=10, last_used=None)
    return PersonaState(
        name="woodworker", version=1, seeds=["woodworking"], topic_tree=[root],
        fingerprint=fp, created_at="2026-03-12T10:00:00Z",
        total_sessions=20, expertise_level=0.4,
    )

def test_select_branch_prefers_less_visited():
    engine = PersonaEngine()
    persona = _make_persona()
    # hand planes has query_count=2, woodworking has 10
    # Over many selections, hand planes should be picked more often
    counts = {"woodworking": 0, "hand planes": 0}
    for _ in range(100):
        branch = engine.select_branch(persona)
        counts[branch.topic] += 1
    assert counts["hand planes"] > counts["woodworking"]

def test_generate_query_sequence():
    engine = PersonaEngine()
    persona = _make_persona()
    branch = persona.topic_tree[0]  # woodworking root
    queries = engine.generate_query_sequence(persona, branch)
    assert 3 <= len(queries) <= 8
    assert all(isinstance(q, str) for q in queries)
    # First query should be related to the branch topic
    assert "woodworking" in queries[0].lower() or len(queries[0]) > 0

def test_build_session_context():
    engine = PersonaEngine()
    persona = _make_persona()
    context = engine.build_session_context(persona)
    assert isinstance(context, SessionContext)
    assert context.persona.name == "woodworker"
    assert 3 <= len(context.queries) <= 8
    assert context.current_query_index == 0
    assert context.session_id  # Should be a non-empty UUID string
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement `engine.py`**

Class `PersonaEngine` with methods:
- `select_branch(persona) -> TopicNode`: weighted random selection favoring low `query_count` and shallow nodes
- `generate_query_sequence(persona, branch) -> list[str]`: build 3-8 queries as a logical research progression. Use topic + depth to adjust specificity. Early queries broad, later ones refine.
- `build_session_context(persona) -> SessionContext`: selects branch, generates queries, creates UUID, returns ready-to-use context

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/murmurate/persona/engine.py tests/test_persona_engine.py
git commit -m "feat: persona engine with branch selection and query sequence generation"
```

---

## Chunk 3: Transport Layer + Plugin Framework

After this chunk, sessions can actually execute network requests and navigate sites.

### Task 10: Transport base interface + plugin ABC

**Files:**
- Create: `src/murmurate/transport/__init__.py`
- Create: `src/murmurate/transport/base.py`
- Create: `src/murmurate/plugins/__init__.py`
- Create: `src/murmurate/plugins/base.py`
- Create: `tests/test_plugin_base.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_plugin_base.py
import pytest
from murmurate.plugins.base import SitePlugin
from murmurate.transport.base import Transport
from murmurate.models import TransportType

def test_site_plugin_is_abstract():
    with pytest.raises(TypeError):
        SitePlugin()

def test_transport_is_abstract():
    with pytest.raises(TypeError):
        Transport()

def test_transport_type_enum_values():
    assert TransportType.HTTP.value == "http"
    assert TransportType.BROWSER.value == "browser"
    assert TransportType.EITHER.value == "either"
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement base classes**

`Transport` ABC with `async def execute_session(self, session: BrowsingSession) -> SessionResult`. `SitePlugin` ABC with attributes (`name`, `domains`, `preferred_transport`, `rate_limit_rpm`) and methods (`execute_search`, `browse_result`) per spec.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/murmurate/transport/ src/murmurate/plugins/ tests/test_plugin_base.py
git commit -m "feat: transport and plugin abstract base classes"
```

---

### Task 11: HTTP transport

**Files:**
- Create: `src/murmurate/transport/http.py`
- Create: `tests/test_transport_http.py`

- [ ] **Step 1: Write failing tests**

Test with `aioresponses` mocking. Test: basic GET, UA rotation from persona fingerprint, redirect following, HTML link extraction, backoff on 429, bot challenge detection (page contains "verify you are human"), DNS failure handling (after 5 consecutive DNS failures, pause 60s). Also test `respect_robots_txt` config option: when True, check robots.txt before requests; when False (default), skip robots.txt entirely.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement `http.py`**

Class `HttpTransport(Transport)`. Uses `aiohttp.ClientSession`. Per-request: sets UA + Accept-Language from persona fingerprint. Implements retry with exponential backoff + jitter on 429/503. Detects CAPTCHA pages via string heuristic. Parses HTML with basic regex or `html.parser` to extract links and text content for `BrowseAction.content_snippets`.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/murmurate/transport/http.py tests/test_transport_http.py
git commit -m "feat: HTTP transport with UA rotation and retry logic"
```

---

### Task 12: Browser transport + pool

**Files:**
- Create: `src/murmurate/transport/browser.py`
- Create: `src/murmurate/transport/pool.py`
- Create: `tests/test_transport_browser.py`
- Create: `tests/test_transport_pool.py`

- [ ] **Step 1: Write failing tests for pool**

Test: pool creates up to N contexts, reuses them, rotates after 20 sessions or 2 hours, queues when full with timeout (falls back to HTTP or skips after timeout), creates fresh profiles per rotation. Also test Playwright graceful degradation: when `playwright` import fails, `BrowserTransport` init raises `ImportError` and caller falls back to HTTP-only mode.

- [ ] **Step 2: Write failing tests for browser transport**

Test: fingerprint profile applied to context (viewport, locale, timezone, UA), `addInitScript` called for canvas/WebGL/hardwareConcurrency overrides, human behavior simulation (typing delay, mouse jitter). Use Playwright's mock/test utilities or mock the Playwright API.

- [ ] **Step 3: Run tests — expect FAIL**

- [ ] **Step 4: Implement `pool.py`**

Class `BrowserPool`. Manages a list of `BrowserContext` objects. `async def acquire(fingerprint, timeout_s) -> BrowserContext`. `async def release(context)`. Tracks session count and creation time per context. Rotates when thresholds exceeded.

- [ ] **Step 5: Implement `browser.py`**

Class `BrowserTransport(Transport)`. Acquires context from pool, applies fingerprint profile (viewport, locale, timezone via context options; canvas noise, WebGL, hardwareConcurrency, deviceMemory via `addInitScript`). Simulates human behavior: random typing speed (40-80 WPM with occasional typos), mouse movement with jitter, scroll patterns, dwell time.

- [ ] **Step 6: Run tests — expect PASS**

- [ ] **Step 7: Commit**

```bash
git add src/murmurate/transport/browser.py src/murmurate/transport/pool.py tests/test_transport_browser.py tests/test_transport_pool.py
git commit -m "feat: browser transport with fingerprint injection and context pooling"
```

---

### Task 13: Plugin registry + discovery

**Files:**
- Create: `src/murmurate/plugins/registry.py`
- Create: `tests/test_plugin_registry.py`

- [ ] **Step 1: Write failing tests**

Test: discovers bundled plugins, discovers user plugins from config dir, enable/disable via config, plugin info lookup, consecutive failure tracking with auto-disable after 5 failures, re-enable after cooldown.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement `registry.py`**

Class `PluginRegistry`. `load_bundled()` imports from `murmurate.plugins`. `load_user_plugins(plugin_dir)` imports `.py` files. `get_enabled(config) -> list[SitePlugin]`. `record_failure(plugin_name)` / `record_success(plugin_name)` for the 5-consecutive-failure auto-disable logic. `get_plugin_info(name)`.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/murmurate/plugins/registry.py tests/test_plugin_registry.py
git commit -m "feat: plugin registry with discovery and auto-disable on failures"
```

---

### Task 14: First two plugins (DuckDuckGo + Wikipedia)

**Files:**
- Create: `src/murmurate/plugins/duckduckgo.py`
- Create: `src/murmurate/plugins/wikipedia.py`
- Create: `tests/test_plugin_duckduckgo.py`
- Create: `tests/test_plugin_wikipedia.py`

- [ ] **Step 1: Write failing tests for DuckDuckGo plugin**

Test: `execute_search` constructs proper DDG URL from query, parses HTML results. `browse_result` follows a link and extracts content. Use `aioresponses` to mock DDG HTML responses.

- [ ] **Step 2: Write failing tests for Wikipedia plugin**

Test: `execute_search` uses Wikipedia search API or HTML. `browse_result` follows article links, extracts headings and content. Pure HTTP — no browser needed.

- [ ] **Step 3: Run tests — expect FAIL**

- [ ] **Step 4: Implement both plugins**

Each extends `SitePlugin`. DuckDuckGo: `preferred_transport = EITHER`, `rate_limit_rpm = 10`. Wikipedia: `preferred_transport = HTTP`, `rate_limit_rpm = 30`.

- [ ] **Step 5: Run tests — expect PASS**

- [ ] **Step 6: Commit**

```bash
git add src/murmurate/plugins/duckduckgo.py src/murmurate/plugins/wikipedia.py tests/test_plugin_duckduckgo.py tests/test_plugin_wikipedia.py
git commit -m "feat: DuckDuckGo and Wikipedia site plugins"
```

---

## Chunk 4: Scheduler + CLI + Daemon

After this chunk, Murmurate is a working end-to-end tool. You can `murmurate run --sessions 5` and it generates real noise.

### Task 15: Timing model (Poisson + circadian)

**Files:**
- Create: `src/murmurate/scheduler/__init__.py`
- Create: `src/murmurate/scheduler/timing.py`
- Create: `tests/test_timing.py`

- [ ] **Step 1: Write failing tests**

Test: `next_delay()` returns positive float, distribution roughly matches Poisson (over many samples, mean ≈ expected), circadian weighting reduces activity during off-hours and increases during peak hours, quiet hours return very large delays (effectively paused), burst clustering produces occasional short gaps.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement `timing.py`**

Class `TimingModel`. Init with `SchedulerConfig`. Method `next_delay(current_time) -> float` returns seconds until next session. Uses `random.expovariate()` for Poisson, multiplied by a circadian factor derived from gaussian peaks at configured peak hours. Returns `float('inf')` during quiet hours. `should_burst() -> bool` based on `burst_probability`. **Weekend/weekday variance**: `is_weekend(current_time) -> bool` shifts the persona selection weighting (more leisure/shopping on weekends, more professional/academic on weekdays) and slightly adjusts the base session rate (weekends: 0.8x rate, weekdays: 1.0x).

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/murmurate/scheduler/ tests/test_timing.py
git commit -m "feat: Poisson + circadian timing model"
```

---

### Task 16: Rate limiter

**Files:**
- Create: `src/murmurate/scheduler/rate_limiter.py`
- Create: `tests/test_rate_limiter.py`

- [ ] **Step 1: Write failing tests**

Test: `can_request(domain)` returns True when under limit, False when at limit. Per-domain limits respected independently. Global bandwidth tracking. Cleanup of old entries.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement `rate_limiter.py`**

Class `RateLimiter` wrapping `StateDB` rate limit methods. `async def can_request(domain, rpm_limit) -> bool`. `async def record(domain)`. `async def cleanup()`. Periodic cleanup runs every 5 minutes via the scheduler loop.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/murmurate/scheduler/rate_limiter.py tests/test_rate_limiter.py
git commit -m "feat: per-domain rate limiter backed by SQLite"
```

---

### Task 17: Main scheduler

**Files:**
- Create: `src/murmurate/scheduler/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests**

Test: scheduler generates sessions with correct persona/plugin/transport assignments. Respects transport ratio. Sessions execute through transport. Session results logged to database. Plugin failure tracking works. Test with mock transports and plugins.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement `scheduler.py`**

Class `Scheduler`. Init with config, personas, plugin registry, transports, database, timing model, rate limiter. `async def run(max_sessions: int | None = None)`: main loop — compute next delay, sleep, pick persona, pick plugin (weighted by enabled list), pick transport (based on plugin preference + configured ratio), build session, execute session via transport, log result, evolve topic tree, save persona. Handles overlapping sessions via `asyncio.create_task`. Supports `max_sessions` for `murmurate run` mode (None = run forever for daemon).

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/murmurate/scheduler/scheduler.py tests/test_scheduler.py
git commit -m "feat: main scheduler with session orchestration"
```

---

### Task 18: CLI

**Files:**
- Create: `src/murmurate/cli.py`
- Create: `src/murmurate/__main__.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Test with Click's `CliRunner`: `murmurate run --sessions 1` exits cleanly, `murmurate status` prints info, `murmurate personas list` shows personas, `murmurate plugins list` shows plugins. Use mock scheduler/database.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement `cli.py`**

Click group `cli` with commands: `run` (--sessions, --config-dir, --log-format [json|text]), `start` (--config-dir, --background, --log-format), `stop`, `status`, `personas` (subgroup: `list`, `add`), `history` (--last), `stats` (--days), `plugins` (subgroup: `list`, `info`), `install-daemon` (--systemd), `uninstall-daemon`. Each command resolves config dir, loads config, and delegates to the appropriate component. The `--log-format` flag passes through to `setup_logging(json_format=...)`. The `stats` command delegates to a `compute_stats(db, days)` function that queries session history and calculates: mean/stddev gap, Poisson lambda, peak hour analysis, transport split, plugin distribution, topic diversity (unique branches), error count. The `start` command checks `config.personas.auto_generate_count` and creates auto-generated personas from topic pools if fewer than that count exist in the personas dir.

- [ ] **Step 4: Implement `__main__.py`**

```python
from murmurate.cli import cli
cli()
```

- [ ] **Step 5: Run tests — expect PASS**

- [ ] **Step 6: Commit**

```bash
git add src/murmurate/cli.py src/murmurate/__main__.py tests/test_cli.py
git commit -m "feat: Click CLI with all commands"
```

---

### Task 19: Daemon lifecycle

**Files:**
- Create: `src/murmurate/daemon/__init__.py`
- Create: `src/murmurate/daemon/lifecycle.py`
- Create: `src/murmurate/daemon/install.py`
- Create: `tests/test_daemon.py`

- [ ] **Step 1: Write failing tests**

Test: PID file written on start, stale PID detected and cleaned up, refuse to start if already running, SIGTERM triggers graceful shutdown, stop command sends SIGTERM, SIGHUP triggers config + persona reload (mock scheduler's `reload()` method, verify it re-reads config.toml and persona files). Test `install.py`: generates valid launchd plist XML with correct paths and config-dir.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement `lifecycle.py`**

Functions: `write_pid(pid_file)`, `read_pid(pid_file) -> int | None`, `is_running(pid) -> bool`, `check_already_running(pid_file)`, `setup_signal_handlers(scheduler)` (SIGTERM → graceful, SIGINT → immediate, SIGHUP → reload), `stop_daemon(pid_file)`.

- [ ] **Step 4: Implement `install.py`**

Functions: `generate_launchd_plist(config_dir, label="com.murmurate.daemon") -> str`, `install_launchd(config_dir)`, `uninstall_launchd()`, `generate_systemd_unit(config_dir) -> str`.

- [ ] **Step 5: Run tests — expect PASS**

- [ ] **Step 6: Commit**

```bash
git add src/murmurate/daemon/ tests/test_daemon.py
git commit -m "feat: daemon lifecycle with PID management and launchd/systemd install"
```

---

## Chunk 5: Remaining Plugins + Polish

### Task 20: Google plugin

**Files:**
- Create: `src/murmurate/plugins/google.py`
- Create: `tests/test_plugin_google.py`

- [ ] **Step 1: Write failing tests** (mock HTML responses)
- [ ] **Step 2: Implement** — handles "People also ask", follows results, works with both HTTP and Browser transport
- [ ] **Step 3: Run tests — expect PASS**
- [ ] **Step 4: Commit**

### Task 21: YouTube plugin

**Files:**
- Create: `src/murmurate/plugins/youtube.py`

- [ ] **Step 1: Write failing tests** (mock responses, browser-required)
- [ ] **Step 2: Implement** — search + partial video "watching" (navigate to video, wait dwell time, don't actually need to decode video)
- [ ] **Step 3: Run tests — expect PASS**
- [ ] **Step 4: Commit**

### Task 22: Amazon plugin

**Files:**
- Create: `src/murmurate/plugins/amazon.py`

- [ ] **Step 1: Write failing tests**
- [ ] **Step 2: Implement** — product search, browse listings, "read" reviews
- [ ] **Step 3: Run tests — expect PASS**
- [ ] **Step 4: Commit**

### Task 23: Reddit plugin

**Files:**
- Create: `src/murmurate/plugins/reddit.py`

- [ ] **Step 1: Write failing tests**
- [ ] **Step 2: Implement** — old.reddit.com (HTTP-friendly), subreddit browse, thread reading
- [ ] **Step 3: Run tests — expect PASS**
- [ ] **Step 4: Commit**

### Task 24: Bing plugin

**Files:**
- Create: `src/murmurate/plugins/bing.py`

- [ ] **Step 1: Write failing tests**
- [ ] **Step 2: Implement**
- [ ] **Step 3: Run tests — expect PASS**
- [ ] **Step 4: Commit**

### Task 25: End-to-end integration test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

Full pipeline: load config → load personas → init transports (HTTP only, mock responses) → init plugins (DuckDuckGo + Wikipedia) → run scheduler for 3 sessions → verify sessions logged in DB, persona trees evolved, no errors.

- [ ] **Step 2: Run test — expect PASS**

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: end-to-end integration test"
```

### Task 26: Final packaging + README update

- [ ] **Step 1: Verify `pip install -e .` works**
- [ ] **Step 2: Verify `murmurate --help` shows all commands**
- [ ] **Step 3: Verify `murmurate run --sessions 1` executes (with mocked network or real DuckDuckGo)**
- [ ] **Step 4: Update README.md with install instructions and quickstart**
- [ ] **Step 5: Commit**

```bash
git add README.md pyproject.toml
git commit -m "docs: update README with install and quickstart"
```

- [ ] **Step 6: Run full test suite**

```bash
pytest --cov=murmurate --cov-report=term-missing -v
```

- [ ] **Step 7: Tag pre-audit**

```bash
git tag v0.1.0-pre-audit
git push origin main --tags
```
