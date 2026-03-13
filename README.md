# Murmurate

> *A murmuration is a flock of thousands of starlings moving as one — no individual bird can be tracked.*

**Murmurate** generates realistic decoy internet activity to obscure your real browsing patterns. Unlike simple noise generators that spray random queries, Murmurate creates coherent, persona-driven browsing sessions with human-like timing — making the noise statistically indistinguishable from signal.

## Why?

ISPs, search engines, and ad networks build detailed profiles from your browsing history. Existing privacy noise tools (random searches, traffic generators) are trivially filterable — a search engine can easily distinguish "random English nouns at 10-second intervals" from real behavior.

Murmurate takes a different approach:

- **Persona-driven topics** — not random words, but coherent research arcs that evolve over weeks
- **Realistic timing** — Poisson-distributed sessions with circadian patterns, not clockwork intervals
- **Multi-engine coverage** — Google, Bing, DuckDuckGo, YouTube, Amazon, Reddit, Wikipedia
- **Browsing follow-through** — clicks results, dwells on pages, scrolls like a human
- **Plugin architecture** — community-extensible site support

## Features

- Hybrid transport: lightweight HTTP for bulk noise, full Playwright browser for deep sessions
- Background daemon mode with configurable active hours, or on-demand CLI
- Multi-machine sync via cloud storage (iCloud, Syncthing, Dropbox)
- Conservative rate limits — won't trigger CAPTCHAs or abuse detection
- No telemetry, no phone-home, fully open source

## Status

**Design phase** — spec complete, implementation not yet started.

See [SPEC.md](SPEC.md) for the full design document.

## Inspiration

Built on ideas from [Chaff](https://github.com/torchhound/Chaff), [Noisy](https://github.com/1tayH/noisy), [TrackMeNot](https://www.trackmenot.io), [AdNauseam](https://adnauseam.io), [ISP Data Pollution](https://github.com/essandess/isp-data-pollution), and academic research on search obfuscation and differential privacy. See the [Prior Art](SPEC.md#inspiration--prior-art) section of the spec for full citations.

## License

MIT
