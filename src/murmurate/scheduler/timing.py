"""Poisson + circadian timing model for realistic session scheduling."""

import math
import random
from datetime import datetime


class TimingModel:
    """Generates human-like delays between browsing sessions.

    Models inter-session intervals as a Poisson process (exponentially
    distributed wait times) with a rate that varies according to:
      - Time of day (circadian rhythm — gaussian peaks at configured hours)
      - Day of week (weekends get a 0.8x rate reduction)
      - Quiet hours (no activity at all during sleep window)
    """

    def __init__(self, config):
        """
        config is a SchedulerConfig with attributes:
          - sessions_per_hour_min: int (default 3)
          - sessions_per_hour_max: int (default 8)
          - active_hours_start: str "HH:MM" (default "07:00")
          - active_hours_end: str "HH:MM" (default "23:00")
          - peak_hours: list[str] ["HH:MM", ...] (default ["10:00", "20:00"])
          - quiet_hours_start: str "HH:MM" (default "23:30")
          - quiet_hours_end: str "HH:MM" (default "06:30")
          - burst_probability: float 0-1 (default 0.15)
        """
        self._config = config

    def next_delay(self, current_time: datetime) -> float:
        """Return seconds until next session.

        Uses Poisson process (random.expovariate) with rate modulated by:
        1. Base rate from sessions_per_hour range
        2. Circadian factor — gaussian peaks at configured peak_hours
        3. Quiet hours — returns float('inf') to effectively pause
        4. Weekend adjustment — 0.8x rate on weekends
        """
        if self._in_quiet_hours(current_time):
            return float('inf')

        base_rate = random.uniform(
            self._config.sessions_per_hour_min,
            self._config.sessions_per_hour_max,
        ) / 3600.0  # Convert to per-second

        circadian = self._circadian_factor(current_time)
        weekend_factor = 0.8 if self.is_weekend(current_time) else 1.0

        effective_rate = base_rate * circadian * weekend_factor
        if effective_rate <= 0:
            return float('inf')

        return random.expovariate(effective_rate)

    def should_burst(self) -> bool:
        """Random check for burst session.

        A burst represents a sudden spike in browsing activity — e.g., when
        a user gets engrossed in reading and fires off many requests quickly.
        """
        return random.random() < self._config.burst_probability

    @staticmethod
    def is_weekend(current_time: datetime) -> bool:
        """Return True if current_time falls on a weekend.

        Saturday=5, Sunday=6 in Python's weekday() convention.
        """
        return current_time.weekday() >= 5

    def _in_quiet_hours(self, current_time: datetime) -> bool:
        """Check if current_time falls in the configured quiet hours window.

        Handles midnight wraparound correctly — e.g., quiet_hours_start=23:30
        and quiet_hours_end=06:30 means the window spans overnight. A time like
        00:30 or 05:00 should still be considered quiet even though it's
        numerically less than the start time.
        """
        # Convert quiet hour boundaries to total minutes since midnight for
        # easy comparison against the current time.
        qs_h, qs_m = map(int, self._config.quiet_hours_start.split(":"))
        qe_h, qe_m = map(int, self._config.quiet_hours_end.split(":"))

        quiet_start = qs_h * 60 + qs_m
        quiet_end = qe_h * 60 + qe_m
        current_minutes = current_time.hour * 60 + current_time.minute

        if quiet_start < quiet_end:
            # Simple case: quiet window does NOT wrap around midnight
            # e.g., 01:00 - 06:00
            return quiet_start <= current_minutes < quiet_end
        else:
            # Wraparound case: quiet window crosses midnight
            # e.g., 23:30 - 06:30 means quiet if >= 23:30 OR < 06:30
            return current_minutes >= quiet_start or current_minutes < quiet_end

    def _circadian_factor(self, current_time: datetime) -> float:
        """Gaussian weighting based on proximity to configured peak hours.

        Returns a value in the 0.2-1.0 range — never zero so there is always
        some baseline probability of activity even during off-peak periods.

        Each peak_hour contributes a gaussian bump (sigma=2 hours). The
        maximum contribution across all peaks is taken, which means the factor
        approaches 1.0 when the current time is near any peak hour and decays
        smoothly toward the 0.2 floor as the time moves away from all peaks.

        Circular distance is used so that a time like 23:50 is correctly
        treated as close to a midnight peak rather than far from it.
        """
        hour_float = current_time.hour + current_time.minute / 60.0
        # Start at 0.2 — the minimum baseline factor (never fully suppress activity)
        max_factor = 0.2

        for peak_str in self._config.peak_hours:
            peak_h, peak_m = map(int, peak_str.split(":"))
            peak = peak_h + peak_m / 60.0
            # Use circular distance on a 24-hour clock so e.g. 23:00 and 01:00
            # are treated as 2 hours apart rather than 22 hours apart.
            dist = min(abs(hour_float - peak), 24 - abs(hour_float - peak))
            # Gaussian with sigma=2 hours
            factor = math.exp(-0.5 * (dist / 2.0) ** 2)
            max_factor = max(max_factor, factor)

        return max_factor
