"""
models.py — Core data model definitions for Murmurate.

All models are plain dataclasses to keep them lightweight and serializable.
They represent the primary entities that flow through the system:
  - Persona / identity management (PersonaState, FingerprintProfile)
  - Topic tree for guiding browsing behavior (TopicNode)
  - Session lifecycle (BrowsingSession, SessionContext, SessionResult)
  - Per-action records (SearchResult, BrowseAction)
"""

from dataclasses import dataclass, field
from enum import Enum


class TransportType(Enum):
    """
    How a browsing session connects to the internet.

    HTTP  — uses aiohttp; faster, lower overhead, no JS execution.
    BROWSER — uses Playwright; slower but renders pages, executes JS,
              and supports full fingerprinting via canvas/WebGL hooks.
    EITHER — the scheduler may choose based on the plugin's needs and
             system load.
    """
    HTTP = "http"
    BROWSER = "browser"
    EITHER = "either"


@dataclass
class TopicNode:
    """
    A node in the hierarchical topic tree that guides what a persona searches for.

    The tree is seeded from the persona's `seeds` list and expanded over time
    via TF-IDF clustering of prior results. `depth` tracks how many levels down
    from the root this node lives (0 = root / seed topic).
    """
    topic: str
    depth: int
    children: list["TopicNode"] = field(default_factory=list)
    # How many times this node has been used as a query source
    query_count: int = 0
    # ISO-8601 timestamp of the last session that used this node
    last_used: str | None = None


@dataclass
class FingerprintProfile:
    """
    Browser fingerprint data for a persona.

    Populated once at persona creation and rotated periodically to simulate
    hardware/OS changes. Every field corresponds to a JS-observable browser
    property that fingerprinting scripts typically capture.
    """
    platform: str               # e.g. "Win32", "MacIntel", "Linux x86_64"
    user_agent: str
    screen_width: int
    screen_height: int
    viewport_width: int
    viewport_height: int
    timezone_id: str            # IANA tz name, e.g. "America/Chicago"
    locale: str                 # BCP-47, e.g. "en-US"
    accept_language: str        # HTTP Accept-Language header value
    hardware_concurrency: int   # navigator.hardwareConcurrency (logical CPUs)
    device_memory: int          # navigator.deviceMemory (GB, power-of-2)
    webgl_vendor: str           # UNMASKED_VENDOR_WEBGL
    webgl_renderer: str         # UNMASKED_RENDERER_WEBGL
    # Seed for deterministic canvas noise injection — same seed = same noise per session
    canvas_noise_seed: int
    fonts: list[str]            # Installed font list to expose via canvas probing
    created_at: str             # ISO-8601
    last_rotated: str | None = None  # ISO-8601; None if never rotated


@dataclass
class PersonaState:
    """
    Full state for a single synthetic persona.

    A persona combines an identity (name, fingerprint) with a browsing
    history model (topic_tree, expertise_level) and session statistics.
    Serialized to SQLite between sessions.
    """
    name: str
    version: int                # Incremented on every save for optimistic concurrency
    seeds: list[str]            # Initial topic keywords that seeded the topic tree
    topic_tree: list[TopicNode] # Root nodes; children are nested inside each node
    fingerprint: FingerprintProfile
    created_at: str             # ISO-8601
    total_sessions: int = 0
    # 0.0–1.0 float representing how deeply the persona explores vs. staying shallow
    expertise_level: float = 0.0


@dataclass
class SessionContext:
    """
    Runtime context passed to a plugin during an active browsing session.

    Provides the plugin with everything it needs to generate realistic,
    persona-coherent behavior: who is browsing, what they're looking for,
    and what they've seen before.
    """
    persona: PersonaState
    queries: list[str]          # Pre-generated query strings for this session
    current_query_index: int    # Index into `queries` for the current step
    topic_branch: TopicNode     # The node in the topic tree driving this session
    expertise_level: float      # Snapshot of persona.expertise_level at session start
    prior_results: list[str]    # URLs visited in previous sessions (for deduplication)
    session_id: str             # UUID4 string


@dataclass
class BrowsingSession:
    """
    A scheduled unit of work: one persona, one plugin, one block of time.

    Created by the scheduler and handed to the runner. The runner executes
    it and produces a SessionResult.
    """
    session_id: str
    persona_name: str
    plugin_name: str
    context: SessionContext
    transport_type: TransportType
    estimated_duration_s: int   # Soft target; runner may exceed slightly
    scheduled_at: str           # ISO-8601


@dataclass
class SearchResult:
    """
    A single result entry from a SERP (search engine results page).

    Scraped/parsed by a plugin during the search phase of a session.
    `position` is 1-indexed, matching how SERPs present results.
    """
    title: str
    url: str
    snippet: str
    position: int


@dataclass
class BrowseAction:
    """
    Record of a single page visit within a session.

    Captured after the runner navigates to and dwells on a URL. Used for
    both logging and feeding back into topic tree expansion.
    """
    url_visited: str
    dwell_time_s: float         # Seconds actually spent on page (simulated)
    links_found: list[str]      # Outbound links harvested for potential follow-on visits
    content_snippets: list[str] # Short text samples for TF-IDF topic expansion
    status_code: int


@dataclass
class SessionResult:
    """
    Post-session summary written to the database after a BrowsingSession completes.

    Aggregates statistics and carries forward any new subtopics discovered during
    the session so the scheduler can enrich the persona's topic tree.
    """
    session_id: str
    persona_name: str
    plugin_name: str
    transport_type: TransportType
    queries_executed: int
    results_browsed: int
    total_duration_s: float
    new_subtopics: list[str]    # Topics extracted from content; merged into topic_tree
    errors: list[str]           # Non-fatal error messages encountered during the session
    completed_at: str           # ISO-8601
    machine_id: str             # Hostname or UUID of the machine that ran the session
