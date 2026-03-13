# Murmurate

Privacy through noise — generate realistic decoy internet activity to obscure your real browsing patterns.

Murmurate creates synthetic browsing personas that search, browse, and read content across popular sites with human-like timing and behavior. Each persona maintains coherent interest profiles, realistic browser fingerprints, and natural activity patterns.

## Why Murmurate?

Existing tools like [TrackMeNot](https://trackmenot.io/) and AdNauseam generate random noise that's easily filtered by traffic analysis. Murmurate takes a different approach:

- **Persona-driven**: Each synthetic identity has coherent interests that evolve naturally over time via TF-IDF topic extraction
- **Human timing**: Poisson-distributed sessions with circadian rhythm modeling — sessions cluster during "peak hours" and pause during sleep
- **Fingerprint diversity**: Each persona gets a unique, consistent browser fingerprint sampled from real-world distribution data (screen resolution, WebGL renderer, canvas noise, fonts, timezone)
- **Dual transport**: Lightweight HTTP (aiohttp) for most sessions, full Playwright browser automation for JS-heavy sites — configurable ratio
- **Multi-machine**: Personas sync across machines via shared config (iCloud, Syncthing, etc.), each machine runs sessions independently

## Installation

```bash
pip install murmurate

# For browser automation support (optional):
pip install murmurate[browser]
playwright install chromium
```

## Quick Start

```bash
# Create a persona
murmurate personas add alice --seeds cooking --seeds travel --seeds photography

# Run 5 browsing sessions
murmurate run --sessions 5

# Check status
murmurate status

# View recent activity
murmurate history --last 20

# List available plugins
murmurate plugins list
```

## Configuration

Murmurate reads config from `~/.config/murmurate/config.toml`:

```toml
config_version = 1

[scheduler]
sessions_per_hour = { min = 3, max = 8 }
peak_hours = ["10:00", "20:00"]
quiet_hours_start = "23:30"
quiet_hours_end = "06:30"
burst_probability = 0.15

[transport]
http_ratio = 0.7
browser_pool_size = 2

[rate_limit]
default_per_domain_rpm = 10

[persona]
max_topic_depth = 5
auto_generate_count = 3
```

## Bundled Plugins

| Plugin | Transport | Rate Limit | Description |
|--------|-----------|------------|-------------|
| DuckDuckGo | HTTP/Browser | 10 RPM | Privacy-focused search |
| Wikipedia | HTTP | 30 RPM | Article reading |
| Google | HTTP/Browser | 10 RPM | Web search |
| YouTube | Browser | 5 RPM | Video "watching" |
| Amazon | HTTP/Browser | 8 RPM | Product browsing |
| Reddit | HTTP | 15 RPM | Thread reading |
| Bing | HTTP/Browser | 12 RPM | Web search |

## Custom Plugins

Drop a `.py` file in `~/.config/murmurate/plugins/`:

```python
from murmurate.plugins.base import SitePlugin
from murmurate.models import TransportType, SessionContext, SearchResult, BrowseAction

class MyPlugin(SitePlugin):
    @property
    def name(self): return "mysite"

    @property
    def domains(self): return ["mysite.com"]

    @property
    def preferred_transport(self): return TransportType.HTTP

    @property
    def rate_limit_rpm(self): return 10

    async def execute_search(self, context, transport):
        # Your search logic here
        ...

    async def browse_result(self, result, context, transport):
        # Your browse logic here
        ...
```

## Daemon Installation

```bash
# macOS (launchd)
murmurate install-daemon

# Linux (systemd)
murmurate install-daemon --systemd
```

## Prior Art & Inspiration

- [TrackMeNot](https://trackmenot.io/) — browser extension generating random search queries
- [AdNauseam](https://adnauseam.io/) — clicks ads in the background to pollute ad profiles
- [Chaff](https://github.com/torchhound/Chaff) — generates fake web traffic
- EFF [Cover Your Tracks](https://coveryourtracks.eff.org/) — fingerprint distribution data

## License

MIT — Copyright (c) 2026 1507 Systems
