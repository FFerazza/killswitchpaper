"""Time utilities.

Convention (README): all timestamps are UTC; storage uses unix seconds,
logs use ISO 8601.
"""

from collections.abc import Iterator
from datetime import datetime, timezone


def to_unix(iso: str) -> int:
    """Parse an ISO 8601 string (e.g. from config YAML) to unix seconds, UTC.

    Naive datetimes are interpreted as UTC.
    """
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def to_iso(ts: int) -> str:
    """Format unix seconds as an ISO 8601 UTC string for logs."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot_times(start: int, end: int, interval_hours: int) -> Iterator[int]:
    """Yield RIB snapshot times: multiples of `interval_hours` from 00:00 UTC.

    Times are aligned to the UTC day grid (00:00, 08:00, 16:00 for 8h), so
    resumed runs always regenerate the same snapshot set.
    """
    step = interval_hours * 3600
    first = ((start + step - 1) // step) * step
    for ts in range(first, end, step):
        yield ts
