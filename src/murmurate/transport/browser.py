"""
transport/browser.py — Playwright-based browser transport.

BrowserTransport drives a real Chromium/Firefox/WebKit browser through
Playwright, applying per-persona fingerprint overrides at the JS level and
simulating basic human-like behaviour (scroll jitter, mouse movement, dwell
time) to reduce bot-detection surface.

Design choices:
  - Fingerprint injection via add_init_script(): the script runs before any
    page JS so overrides are in place when the page's own fingerprinting
    probes fire.
  - Canvas noise: we XOR each pixel with a deterministic seed-derived value
    so canvas fingerprint reads return a consistent-but-unique result per
    persona rather than the browser's true reading.
  - BrowserPool: contexts are reused (with rotation) to amortise the startup
    cost of new_context() and to simulate realistic cookie/session continuity
    within a persona's lifetime.
  - Playwright is NOT imported at module level — it is an optional dependency
    (`pip install murmurate[browser]`) and its absence must not break imports
    of this module by the core scheduler.

Note: BrowserTransport does NOT subclass Transport (the ABC requires
execute_session which belongs to the plugin+scheduler layer).  The Transport
ABC is deliberately kept thin; BrowserTransport exposes navigate() which the
plugin layer calls directly.
"""

from __future__ import annotations

import asyncio
import random

from murmurate.transport.pool import BrowserPool
from murmurate.models import FingerprintProfile


class BrowserTransport:
    """
    Playwright browser transport with fingerprint injection and context pooling.

    Each navigate() call:
      1. Acquires a BrowserContext from the pool.
      2. Installs the JS fingerprint init-script on the context.
      3. Opens a new page and navigates to the target URL.
      4. Simulates a brief human-like interaction (scroll + mouse jitter).
      5. Dwells for dwell_time_s seconds.
      6. Extracts and returns the page HTML.
      7. Releases the context back to the pool (always, even on error).
    """

    def __init__(self, pool: BrowserPool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Core public method
    # ------------------------------------------------------------------

    async def navigate(
        self,
        url: str,
        fingerprint: FingerprintProfile,
        dwell_time_s: float = 2.0,
    ) -> str:
        """
        Navigate to url using a fingerprint-configured browser context.

        Args:
            url:          The page to load.
            fingerprint:  Persona fingerprint — drives context settings and
                          JS overrides.
            dwell_time_s: Seconds to wait after the page loads (simulates
                          reading / looking at content).  Set to 0 in tests.

        Returns:
            Full page HTML from page.content().

        Raises:
            Re-raises any exception from Playwright after releasing the context.
        """
        pooled = await self._pool.acquire(fingerprint)
        try:
            ctx = pooled.context

            # Install the JS overrides before the page makes any requests.
            # add_init_script() guarantees the script runs ahead of page JS.
            init_script = self.build_init_script(fingerprint)
            await ctx.add_init_script(script=init_script)

            page = await ctx.new_page()
            await page.goto(url)

            # Simulate basic human interaction — prevents trivial bot detection
            # heuristics based on zero scroll / zero mouse movement.
            await self._simulate_human_behaviour(page)

            if dwell_time_s > 0:
                await asyncio.sleep(dwell_time_s)

            html = await page.content()

        except Exception:
            # Release before re-raising so the pool isn't permanently depleted
            await self._pool.release(pooled)
            raise

        # Always release on the happy path too
        await self._pool.release(pooled)
        return html

    # ------------------------------------------------------------------
    # Human behaviour simulation
    # ------------------------------------------------------------------

    @staticmethod
    async def _simulate_human_behaviour(page) -> None:
        """
        Perform minimal realistic-looking interactions on the page.

        We use page.evaluate() for scroll (avoids needing a visible element)
        and page.mouse.move() for micro mouse-jitter.  Both are lightweight
        and don't depend on page structure, so they're safe to call on any URL.

        Values are randomised per call so repeated sessions don't produce
        identical interaction fingerprints.
        """
        try:
            # Scroll down a random amount, then back up slightly
            scroll_y = random.randint(100, 600)
            await page.evaluate(f"window.scrollTo(0, {scroll_y})")
            back_y = random.randint(0, scroll_y // 2)
            await page.evaluate(f"window.scrollTo(0, {back_y})")

            # Jitter mouse to a random viewport position
            x = random.randint(50, 800)
            y = random.randint(50, 500)
            await page.mouse.move(x, y)
        except Exception:
            # Simulation is best-effort — never let it abort a real session
            pass

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_init_script(fingerprint: FingerprintProfile) -> str:
        """
        Build the JavaScript init script that overrides fingerprint-detectable APIs.

        The script is injected via Playwright's add_init_script() which runs
        before any page JavaScript, so overrides are in place when fingerprinting
        libraries probe the browser environment.

        Overrides applied:
          - navigator.hardwareConcurrency — logical CPU count
          - navigator.deviceMemory       — RAM in GB (power-of-two buckets)
          - WebGL UNMASKED_VENDOR_WEBGL  — GPU vendor string
          - WebGL UNMASKED_RENDERER_WEBGL — GPU renderer/model string
          - HTMLCanvasElement.toDataURL  — adds deterministic per-pixel noise
            so each persona has a stable but unique canvas fingerprint

        Args:
            fingerprint: The FingerprintProfile whose values to bake into the script.

        Returns:
            A JavaScript string safe to pass to add_init_script().
        """
        hw = fingerprint.hardware_concurrency
        dm = fingerprint.device_memory
        vendor = fingerprint.webgl_vendor.replace("'", "\\'")
        renderer = fingerprint.webgl_renderer.replace("'", "\\'")
        seed = fingerprint.canvas_noise_seed

        return f"""
(function() {{
  // ── navigator overrides ───────────────────────────────────────────
  // Define these as non-configurable getters so fingerprinting scripts
  // that check Object.getOwnPropertyDescriptor() still get our values.
  Object.defineProperty(navigator, 'hardwareConcurrency', {{
    get: () => {hw},
    configurable: true,
  }});
  Object.defineProperty(navigator, 'deviceMemory', {{
    get: () => {dm},
    configurable: true,
  }});

  // ── WebGL vendor / renderer override ─────────────────────────────
  // We wrap getContext to intercept the WebGL rendering context and
  // patch its getParameter() method for the two UNMASKED_* constants.
  const _getContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function(type, ...args) {{
    const ctx = _getContext.apply(this, [type, ...args]);
    if (ctx && (type === 'webgl' || type === 'experimental-webgl' || type === 'webgl2')) {{
      const ext = ctx.getExtension('WEBGL_debug_renderer_info');
      if (ext) {{
        const _getParameter = ctx.getParameter.bind(ctx);
        ctx.getParameter = function(param) {{
          if (param === ext.UNMASKED_VENDOR_WEBGL) return '{vendor}';
          if (param === ext.UNMASKED_RENDERER_WEBGL) return '{renderer}';
          return _getParameter(param);
        }};
      }}
    }}
    return ctx;
  }};

  // ── Canvas noise injection ────────────────────────────────────────
  // Replace toDataURL with a version that adds deterministic per-pixel
  // noise derived from the seed.  The XOR value is tiny (0–3) so the
  // visual change is invisible but the fingerprint hash differs from
  // the browser's true reading.  Using a fixed seed ensures the same
  // persona always produces the same canvas fingerprint.
  const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function(...args) {{
    const seed = {seed};
    const ctx2d = this.getContext('2d');
    if (ctx2d) {{
      const imgData = ctx2d.getImageData(0, 0, this.width || 1, this.height || 1);
      const d = imgData.data;
      // Simple LCG PRNG seeded per persona for deterministic noise
      let rng = seed;
      for (let i = 0; i < d.length; i += 4) {{
        rng = (rng * 1664525 + 1013904223) & 0xffffffff;
        const noise = rng & 3;  // 0–3 per-channel noise
        d[i]     = (d[i]     + noise) & 0xff;
        d[i + 1] = (d[i + 1] + noise) & 0xff;
        d[i + 2] = (d[i + 2] + noise) & 0xff;
        // Alpha channel left untouched to avoid transparency glitches
      }}
      ctx2d.putImageData(imgData, 0, 0);
    }}
    return _toDataURL.apply(this, args);
  }};
}})();
"""

    @staticmethod
    def typing_delay_ms(wpm: int = 60) -> float:
        """
        Calculate a realistic per-character typing delay in milliseconds.

        At 60 WPM, assuming ~5 characters per word, the average character rate
        is 300 chars/min → ~200 ms/char.  We add ±30% jitter to simulate the
        natural variance in human typing speed between characters.

        Args:
            wpm: Words per minute (default 60, a realistic average typist).

        Returns:
            Per-character delay in milliseconds, with random jitter applied.
        """
        # 5 chars/word is the standard assumption for WPM calculations
        chars_per_minute = wpm * 5
        base_delay_ms = 60_000.0 / chars_per_minute  # ms per character
        # Apply ±30% jitter to avoid a perfectly metronomic typing pattern
        jitter = random.uniform(0.7, 1.3)
        return base_delay_ms * jitter
