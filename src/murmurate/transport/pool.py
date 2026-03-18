"""
transport/pool.py — Playwright browser context pool.

Maintains a fixed-size pool of Playwright BrowserContexts that are reused
across sessions to amortize the cost of context creation (which involves
loading browser state, cookies, etc.).

Rotation policy:
  - max_sessions: after a context has been used this many times, it is
    closed and removed from the pool.  The next acquire() will create a
    fresh one with clean state (no accumulated cookies / localStorage).
  - max_age_s: contexts older than this threshold are also rotated out,
    preventing long-lived sessions whose fingerprint drift could correlate
    with repeated visits.

Pool blocking:
  - If all contexts are in_use and the pool is at max_size, acquire() waits
    (polling at 50 ms intervals) up to acquire_timeout_s for a slot to free.
  - TimeoutError is raised if the wait exceeds the threshold.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class PooledContext:
    """
    Wraps a Playwright BrowserContext and tracks its lifecycle metadata.

    `session_count` is incremented on every release so the pool can enforce
    max_sessions rotation.  `created_at` is a monotonic timestamp so the
    pool can enforce max_age_s rotation.
    """
    context: object          # playwright.async_api.BrowserContext
    created_at: float        # time.monotonic() at creation
    session_count: int = 0
    in_use: bool = False


class BrowserPool:
    """
    Manages reusable Playwright browser contexts with a rotation policy.

    Usage:
        pool = BrowserPool(browser, max_size=3)
        pooled = await pool.acquire(fingerprint)
        try:
            page = await pooled.context.new_page()
            ...
        finally:
            await pool.release(pooled)
        await pool.close_all()   # on shutdown
    """

    def __init__(
        self,
        browser,                          # playwright.async_api.Browser
        max_size: int = 3,
        max_sessions: int = 20,
        max_age_s: float = 7200.0,
        acquire_timeout_s: float = 60.0,
    ) -> None:
        self._browser = browser
        self._max_size = max_size
        self._max_sessions = max_sessions
        self._max_age_s = max_age_s
        self._acquire_timeout_s = acquire_timeout_s
        self._contexts: list[PooledContext] = []
        # Lock serialises mutations to _contexts so concurrent acquire/release
        # calls don't race when checking pool size or the in_use flag.
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(self, fingerprint) -> PooledContext:
        """
        Return a PooledContext ready for use.

        Selection order:
        1. Return an existing free context (not in_use, not stale).
        2. Create a new context if pool has room.
        3. Wait up to acquire_timeout_s for any context to become free.

        Args:
            fingerprint: FingerprintProfile whose settings are applied to
                         new contexts (viewport, locale, timezone, UA).

        Returns:
            A PooledContext with in_use=True.

        Raises:
            TimeoutError: if the pool is full and no context frees within
                          acquire_timeout_s seconds.
        """
        deadline = time.monotonic() + self._acquire_timeout_s

        while True:
            async with self._lock:
                # 1. Try to reuse an idle, non-stale context
                for pooled in self._contexts:
                    if not pooled.in_use and not self._needs_rotation(pooled):
                        pooled.in_use = True
                        return pooled

                # 2. Create a new context if below capacity
                if len(self._contexts) < self._max_size:
                    ctx = await self._create_context(fingerprint)
                    pooled = PooledContext(context=ctx, created_at=time.monotonic(), in_use=True)
                    self._contexts.append(pooled)
                    return pooled

            # 3. Pool is full — wait and retry
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"BrowserPool: all {self._max_size} contexts in use; "
                    f"timed out after {self._acquire_timeout_s}s"
                )
            # Poll at 50 ms to avoid busy-spinning while releasing the GIL
            await asyncio.sleep(0.05)

    async def release(self, pooled: PooledContext) -> None:
        """
        Return a context to the pool after a session completes.

        Increments session_count.  If the context has hit max_sessions or
        max_age_s it is closed and removed; the pool will create a fresh one
        on the next acquire().

        Args:
            pooled: The PooledContext previously returned by acquire().
        """
        async with self._lock:
            pooled.session_count += 1

            if self._needs_rotation(pooled):
                # Close the browser context (releases its cookies, storage, etc.)
                await pooled.context.close()
                # Remove from pool so next acquire() creates a clean replacement
                try:
                    self._contexts.remove(pooled)
                except ValueError:
                    pass  # Already removed (shouldn't happen, but be safe)
            else:
                # Return to available state for the next acquire()
                pooled.in_use = False

    def _needs_rotation(self, pooled: PooledContext) -> bool:
        """
        Return True if this context should be retired.

        A context is retired when it has served max_sessions requests (cookie
        accumulation risk) or when it is older than max_age_s (fingerprint
        drift / long-term correlation risk).
        """
        age = time.monotonic() - pooled.created_at
        return pooled.session_count >= self._max_sessions or age >= self._max_age_s

    async def _create_context(self, fingerprint) -> object:
        """
        Create a new Playwright BrowserContext applying fingerprint settings.

        Playwright's new_context() accepts viewport, locale, timezone, and
        user_agent directly.  These must match the JS-level overrides injected
        via add_init_script() in BrowserTransport so the values are consistent
        (e.g., navigator.language matches the Accept-Language header).
        """
        return await self._browser.new_context(
            viewport={
                "width": fingerprint.viewport_width,
                "height": fingerprint.viewport_height,
            },
            locale=fingerprint.locale,
            timezone_id=fingerprint.timezone_id,
            user_agent=fingerprint.user_agent,
        )

    async def close_all(self) -> None:
        """
        Close every tracked context and clear the pool.

        Called during daemon shutdown or test teardown.  Safe to call on an
        already-empty pool.
        """
        async with self._lock:
            for pooled in list(self._contexts):
                try:
                    await pooled.context.close()
                except Exception:
                    # Best-effort cleanup — don't let one failure block the rest
                    pass
            self._contexts.clear()

    # ------------------------------------------------------------------
    # Introspection properties
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Total number of contexts currently tracked (in use or free)."""
        return len(self._contexts)

    @property
    def available(self) -> int:
        """Number of free (not in_use) contexts currently in the pool."""
        return sum(1 for c in self._contexts if not c.in_use)
