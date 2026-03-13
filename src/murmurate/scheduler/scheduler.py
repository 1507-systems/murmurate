"""
scheduler.py — Main scheduler orchestrating persona sessions through transports and plugins.

The Scheduler is the central coordination point for Murmurate:
  1. It picks a persona and plugin for each session using weighted/random selection.
  2. It enforces rate limits per domain and realistic inter-session timing.
  3. It delegates execution to the appropriate transport (HTTP or Browser).
  4. It feeds browse results back into the topic evolution pipeline.
  5. It persists session state to the database for observability and replay.

Design notes:
  - run() is the main async loop; call stop() from a signal handler to exit cleanly.
  - reload() is designed for SIGHUP — swap config/personas without restarting.
  - All transport and DB dependencies are injected so the scheduler is testable
    with mocks; no concrete imports of transports or DB are required here.
"""

import asyncio
import logging
import random
import socket
from datetime import datetime, timezone

from murmurate.config import MurmurateConfig
from murmurate.models import BrowsingSession, SessionResult, TransportType
from murmurate.persona.engine import PersonaEngine
from murmurate.persona.evolution import evolve_topic_tree, extract_subtopics
from murmurate.plugins.registry import PluginRegistry
from murmurate.scheduler.timing import TimingModel
from murmurate.scheduler.rate_limiter import RateLimiter
from murmurate.database import StateDB

logger = logging.getLogger(__name__)


class Scheduler:
    """Orchestrates browsing sessions with realistic timing.

    The scheduler owns the main run-loop and delegates to pluggable components:
      - TimingModel: when to fire the next session
      - PersonaEngine: which topic branch / queries to use
      - PluginRegistry: which site plugin to execute
      - RateLimiter: per-domain throttling
      - HttpTransport / BrowserTransport: network layer
      - StateDB: persistence

    All dependencies are constructor-injected so unit tests can mock any layer.
    """

    def __init__(
        self,
        config: MurmurateConfig,
        personas: list,              # list[PersonaState]
        registry: PluginRegistry,
        http_transport,              # HttpTransport
        browser_transport,           # BrowserTransport | None
        db: StateDB,
        timing: TimingModel,
        rate_limiter: RateLimiter,
        persona_engine: PersonaEngine | None = None,
    ) -> None:
        self._config = config
        self._personas = personas
        self._registry = registry
        self._http = http_transport
        self._browser = browser_transport
        self._db = db
        self._timing = timing
        self._rate_limiter = rate_limiter
        # Allow injection for testing; fall back to a default instance
        self._engine = persona_engine or PersonaEngine()
        self._running = False
        # Set by stop() before or during a run() call; checked at loop entry
        self._stop_requested = False
        # Used in SessionResult.machine_id to identify which host ran the session
        self._machine_id = socket.gethostname()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, max_sessions: int | None = None) -> list[SessionResult]:
        """Main scheduling loop.

        Continuously picks a persona + plugin, waits the appropriate delay,
        executes the session, and records the result. Exits when:
          - max_sessions session attempts have been made (if set), or
          - stop() is called from outside.

        An "attempt" is counted each time we reach the session execution step
        (after persona/plugin selection), regardless of whether the session
        succeeds or fails. Skipped iterations (quiet hours, no plugins, rate
        limited) do not count as attempts.

        Args:
            max_sessions: If given, stop after this many session attempts.
                          If None, run until stop() is called.

        Returns:
            List of SessionResult for each successfully completed session.
        """
        # Activate the running state. If stop() was called before run() starts,
        # _stop_requested will be True and the while-condition exits immediately.
        # We do NOT reset _stop_requested here — a pre-run stop() must be honoured.
        self._running = True

        results: list[SessionResult] = []
        session_count = 0   # Counts attempts, not just successes

        while self._running and not self._stop_requested:
            # Respect the max_sessions ceiling
            if max_sessions is not None and session_count >= max_sessions:
                break

            # Ask the timing model how long to wait
            now = datetime.now(timezone.utc)
            delay = self._timing.next_delay(now)

            if delay == float("inf"):
                # Quiet hours — check again in 5 minutes instead of busy-waiting
                await asyncio.sleep(300)
                continue

            if delay > 0:
                # Cap individual sleeps at 60 s so that stop() is responsive
                await asyncio.sleep(min(delay, 60))

            # Check again after sleeping — stop() may have been called while we waited
            if not self._running or self._stop_requested:
                break

            # --- Pick persona (uniform random; could be weighted in future) ---
            persona = random.choice(self._personas)

            # --- Pick plugin ---
            plugins = self._registry.get_enabled()
            if not plugins:
                logger.warning("No enabled plugins available; sleeping 60 s")
                await asyncio.sleep(60)
                continue
            plugin = random.choice(plugins)

            # --- Rate-limit check: skip this tick if any domain is throttled ---
            rate_limited = False
            for domain in plugin.domains:
                if not await self._rate_limiter.can_request(domain, plugin.rate_limit_rpm):
                    logger.debug("Rate limited for %s, skipping session", domain)
                    rate_limited = True
                    break
            if rate_limited:
                continue

            # --- Choose transport based on plugin preference and config ratio ---
            transport_type = self._select_transport(plugin.preferred_transport)
            transport = (
                self._browser
                if transport_type == TransportType.BROWSER and self._browser
                else self._http
            )

            # --- Build session context (selects topic branch, generates queries) ---
            context = self._engine.build_session_context(persona)

            session = BrowsingSession(
                session_id=context.session_id,
                persona_name=persona.name,
                plugin_name=plugin.name,
                context=context,
                transport_type=transport_type,
                estimated_duration_s=random.randint(30, 180),
                scheduled_at=datetime.now(timezone.utc).isoformat(),
            )

            # --- Execute the session ---
            try:
                # Log session start — DB signature: (session_id, persona, plugin, transport, machine)
                await self._db.log_session_start(
                    session.session_id,
                    persona.name,
                    plugin.name,
                    transport_type.value,
                    self._machine_id,
                )

                # Record rate-limit token for each domain before we go out
                for domain in plugin.domains:
                    await self._rate_limiter.record(domain)

                # Phase 1: search — returns a list of SearchResult
                search_results = await plugin.execute_search(context, transport)

                # Phase 2: browse — visit the top few results and collect actions
                actions = []
                for sr in search_results[:3]:   # Browse up to 3 results per session
                    try:
                        action = await plugin.browse_result(sr, context, transport)
                        actions.append(action)
                    except Exception as exc:
                        # Non-fatal — log and continue with the remaining results
                        logger.warning("Failed browsing %s: %s", sr.url, exc)

                # --- Assemble the session result ---
                result = SessionResult(
                    session_id=session.session_id,
                    persona_name=persona.name,
                    plugin_name=plugin.name,
                    transport_type=transport_type,
                    queries_executed=len(context.queries),
                    results_browsed=len(actions),
                    total_duration_s=0.0,   # Placeholder; real timing added in Task 19
                    new_subtopics=[],
                    errors=[],
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    machine_id=self._machine_id,
                )

                # --- Topic evolution: feed content snippets back into the tree ---
                all_snippets: list[str] = []
                for action in actions:
                    all_snippets.extend(action.content_snippets)

                if all_snippets:
                    new_topics = extract_subtopics(
                        parent_topic=context.topic_branch.topic,
                        content_snippets=all_snippets,
                        max_topics=3,
                        drift_rate=self._config.persona.drift_rate,
                    )
                    result.new_subtopics = new_topics
                    # Mutate the persona's topic tree in-place with discovered topics
                    evolve_topic_tree(
                        context.topic_branch,
                        new_topics,
                        max_depth=self._config.persona.max_tree_depth,
                    )

                # Persist completion — DB signature: (session_id, queries, browsed, duration)
                await self._db.log_session_complete(
                    session.session_id,
                    result.queries_executed,
                    result.results_browsed,
                    result.total_duration_s,
                )
                self._registry.record_success(plugin.name)
                results.append(result)

                logger.info(
                    "Session %s complete: plugin=%s persona=%s browsed=%d new_topics=%d",
                    session.session_id[:8],
                    plugin.name,
                    persona.name,
                    result.results_browsed,
                    len(result.new_subtopics),
                )

            except Exception as exc:
                logger.error("Session %s failed: %s", session.session_id[:8], exc)
                await self._db.log_session_failed(session.session_id, str(exc))
                self._registry.record_failure(plugin.name)

            # Count this as an attempt regardless of success/failure so that
            # max_sessions acts as a hard ceiling on total execution attempts.
            session_count += 1

            # --- Burst check: if True, next loop iteration fires with ~zero delay ---
            # The timing model handles this by returning a very small value on the
            # next next_delay() call (via burst_probability in SchedulerConfig).
            # We don't need to do anything special here; leaving the comment for clarity.

        self._running = False
        return results

    def stop(self) -> None:
        """Signal the scheduler to stop after the current session completes.

        Safe to call from a signal handler or from another coroutine, or even
        before run() is called to prevent it from executing at all. The run()
        loop checks _stop_requested at the top of every iteration so it exits
        cleanly without interrupting an in-progress session.
        """
        self._running = False
        self._stop_requested = True

    def reload(self, config: MurmurateConfig, personas: list) -> None:
        """Hot-reload config and personas without restarting the scheduler.

        Intended for SIGHUP handling. The new config takes effect on the next
        iteration of the run loop. In-flight sessions are not affected.
        """
        self._config = config
        self._personas = personas
        # Rebuild timing model so new scheduler settings are applied immediately
        self._timing = TimingModel(config.scheduler)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_transport(self, preferred: TransportType) -> TransportType:
        """Choose a transport based on plugin preference and configured ratio.

        Decision logic:
          - BROWSER preference → BROWSER if available, else HTTP fallback
          - HTTP preference → always HTTP
          - EITHER → probabilistic split using config.transport.browser_ratio;
                     browser branch falls back to HTTP if not available

        Args:
            preferred: The plugin's stated transport preference.

        Returns:
            The resolved TransportType for this session.
        """
        if preferred == TransportType.HTTP:
            return TransportType.HTTP

        if preferred == TransportType.BROWSER:
            return TransportType.BROWSER if self._browser else TransportType.HTTP

        # EITHER — pick based on configured browser_ratio
        # browser_ratio is the fraction of sessions that should use Playwright;
        # use random.random() < browser_ratio to decide "use browser?"
        use_browser = random.random() < self._config.transport.browser_ratio
        if use_browser and self._browser:
            return TransportType.BROWSER
        return TransportType.HTTP
