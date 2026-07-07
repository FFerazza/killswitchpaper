"""Unit tests for time utilities (UTC/unix conventions, snapshot grid)."""

from src.common.timeutil import snapshot_times, to_iso, to_unix, update_times


def test_to_unix_utc():
    assert to_unix("1970-01-01T00:00:00Z") == 0
    assert to_unix("2026-02-28T00:00:00Z") == 1772236800


def test_roundtrip():
    ts = to_unix("2026-02-28T12:34:56Z")
    assert to_iso(ts) == "2026-02-28T12:34:56Z"


def test_snapshot_times_aligned_to_day_grid():
    start = to_unix("2026-02-25T03:00:00Z")
    end = to_unix("2026-02-26T00:00:00Z")
    times = [to_iso(t) for t in snapshot_times(start, end, 8)]
    # first snapshot rounds UP to the next grid point; end is exclusive
    assert times == ["2026-02-25T08:00:00Z", "2026-02-25T16:00:00Z"]


def test_snapshot_times_inclusive_start_on_grid():
    start = to_unix("2026-02-25T00:00:00Z")
    end = to_unix("2026-02-25T16:00:01Z")
    times = [to_iso(t) for t in snapshot_times(start, end, 8)]
    assert times == ["2026-02-25T00:00:00Z", "2026-02-25T08:00:00Z", "2026-02-25T16:00:00Z"]


def test_update_times_5min_grid():
    start = to_unix("2025-06-11T00:00:00Z")
    end = to_unix("2025-06-11T00:15:01Z")
    times = [to_iso(t) for t in update_times(start, end)]
    assert times == [
        "2025-06-11T00:00:00Z", "2025-06-11T00:05:00Z",
        "2025-06-11T00:10:00Z", "2025-06-11T00:15:00Z",
    ]


def test_update_times_off_grid_start_rounds_up():
    start = to_unix("2025-06-11T00:01:00Z")
    end = to_unix("2025-06-11T00:10:00Z")
    times = [to_iso(t) for t in update_times(start, end)]
    assert times == ["2025-06-11T00:05:00Z"]
