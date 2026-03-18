import random
from datetime import datetime
from murmurate.scheduler.timing import TimingModel

class FakeSchedulerConfig:
    sessions_per_hour_min = 3
    sessions_per_hour_max = 8
    active_hours_start = "07:00"
    active_hours_end = "23:00"
    peak_hours = ["10:00", "20:00"]
    quiet_hours_start = "23:30"
    quiet_hours_end = "06:30"
    burst_probability = 0.15

def test_next_delay_positive():
    model = TimingModel(FakeSchedulerConfig())
    # 2pm on a Tuesday — should be active
    t = datetime(2026, 3, 10, 14, 0, 0)
    delay = model.next_delay(t)
    assert delay > 0
    assert delay < float('inf')

def test_quiet_hours_returns_inf():
    model = TimingModel(FakeSchedulerConfig())
    # 2am — quiet hours
    t = datetime(2026, 3, 10, 2, 0, 0)
    delay = model.next_delay(t)
    assert delay == float('inf')

def test_quiet_hours_just_before_end():
    model = TimingModel(FakeSchedulerConfig())
    # 6:00am — still quiet (ends at 6:30)
    t = datetime(2026, 3, 10, 6, 0, 0)
    delay = model.next_delay(t)
    assert delay == float('inf')

def test_active_during_day():
    model = TimingModel(FakeSchedulerConfig())
    # 10am (peak hour) — should be active, short delays on average
    t = datetime(2026, 3, 10, 10, 0, 0)
    delays = [model.next_delay(t) for _ in range(100)]
    mean_delay = sum(delays) / len(delays)
    assert mean_delay < 1200  # Should average well under 20 min at peak

def test_peak_vs_offpeak():
    model = TimingModel(FakeSchedulerConfig())
    random.seed(42)
    peak_t = datetime(2026, 3, 10, 10, 0, 0)  # peak hour
    peak_delays = [model.next_delay(peak_t) for _ in range(200)]

    random.seed(42)
    offpeak_t = datetime(2026, 3, 10, 7, 0, 0)  # just after active start, not peak
    offpeak_delays = [model.next_delay(offpeak_t) for _ in range(200)]

    # Peak should have shorter average delays
    assert sum(peak_delays) / len(peak_delays) < sum(offpeak_delays) / len(offpeak_delays)

def test_weekend_has_lower_rate():
    model = TimingModel(FakeSchedulerConfig())
    # Saturday at noon
    weekend_t = datetime(2026, 3, 14, 12, 0, 0)
    # Tuesday at noon
    weekday_t = datetime(2026, 3, 10, 12, 0, 0)

    random.seed(42)
    weekend_delays = [model.next_delay(weekend_t) for _ in range(500)]
    random.seed(42)
    weekday_delays = [model.next_delay(weekday_t) for _ in range(500)]

    # Weekend should average longer delays (lower rate)
    assert sum(weekend_delays) / len(weekend_delays) > sum(weekday_delays) / len(weekday_delays)

def test_is_weekend():
    assert TimingModel.is_weekend(datetime(2026, 3, 14, 12, 0))  # Saturday
    assert TimingModel.is_weekend(datetime(2026, 3, 15, 12, 0))  # Sunday
    assert not TimingModel.is_weekend(datetime(2026, 3, 10, 12, 0))  # Tuesday

def test_should_burst_probability():
    model = TimingModel(FakeSchedulerConfig())
    random.seed(42)
    bursts = sum(model.should_burst() for _ in range(1000))
    # With p=0.15, expect ~150 ± 30
    assert 100 < bursts < 200

def test_quiet_hours_wraparound():
    """Quiet hours 23:30-06:30 wraps around midnight."""
    model = TimingModel(FakeSchedulerConfig())
    # 23:45 — quiet
    assert model.next_delay(datetime(2026, 3, 10, 23, 45)) == float('inf')
    # 00:30 — quiet
    assert model.next_delay(datetime(2026, 3, 10, 0, 30)) == float('inf')
    # 06:29 — quiet
    assert model.next_delay(datetime(2026, 3, 10, 6, 29)) == float('inf')
    # 06:31 — not quiet
    assert model.next_delay(datetime(2026, 3, 10, 6, 31)) < float('inf')
