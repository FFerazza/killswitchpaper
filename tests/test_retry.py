"""Snapshot-level retry on transient transport errors (D-002 abort semantics preserved)."""

import pytest

from src.bgp.ribs import retry_transport
from src.bgp.stream import StreamTransportError


def test_succeeds_after_transient_failures():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise StreamTransportError("partial file")

    retry_transport(flaky, attempts=3, delay_s=0)
    assert len(calls) == 3


def test_raises_after_exhausting_attempts():
    def always_broken():
        raise StreamTransportError("persistent corruption")

    with pytest.raises(StreamTransportError, match="persistent"):
        retry_transport(always_broken, attempts=2, delay_s=0)


def test_backoff_doubles_between_attempts(monkeypatch):
    import time

    waits = []
    monkeypatch.setattr(time, "sleep", waits.append)

    def always_broken():
        raise StreamTransportError("persistent corruption")

    with pytest.raises(StreamTransportError):
        retry_transport(always_broken, attempts=4, delay_s=60)
    assert waits == [60, 120, 240]


def test_other_errors_are_not_retried():
    calls = []

    def wrong_error():
        calls.append(1)
        raise ValueError("bug, not transport")

    with pytest.raises(ValueError):
        retry_transport(wrong_error, attempts=3, delay_s=0)
    assert len(calls) == 1


def _cfg():
    from types import SimpleNamespace

    return SimpleNamespace(
        rib_interval_hours=8,
        rib_collectors=["route-views2"],
        full_feed_min_prefixes={"ipv4": 1, "ipv6": 1},
        source=lambda key: "https://archive.example.org",
    )


def test_run_ribs_skips_when_both_transports_fail(monkeypatch, tmp_path):
    """A snapshot failing direct fetch AND broker fallback is skipped, the rest
    of the range completes, and the run exits nonzero listing the miss."""
    import src.bgp.ribs as ribs

    bad_ts = 28800  # middle snapshot of three

    def fake_direct(ts, rv_collectors, matcher, full_feed_min, out_path, *a, **kw):
        if ts == bad_ts:
            raise StreamTransportError("wandio partial file")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.touch()

    def broker_always_fails(fn, **kw):
        raise StreamTransportError("broker also broken")

    monkeypatch.setattr(ribs, "process_snapshot_direct", fake_direct)
    monkeypatch.setattr(ribs, "retry_transport", broker_always_fails)

    with pytest.raises(SystemExit, match="1 snapshot\\(s\\) failed.*1970-01-01T08:00"):
        ribs.run_ribs(_cfg(), tmp_path, {"IR": ["10.0.0.0/8"]}, 0, 24 * 3600,
                      rv_cache_dir=tmp_path / "cache")

    assert (tmp_path / "rib_0.parquet").exists()
    assert not (tmp_path / "rib_28800.parquet").exists()
    assert (tmp_path / "rib_57600.parquet").exists()


def test_run_ribs_broker_fallback_rescues_direct_failure(monkeypatch, tmp_path):
    """When direct fetch fails (download exhausted = RuntimeError), the broker
    fallback runs and the snapshot completes without being reported missing."""
    import src.bgp.ribs as ribs

    def direct_always_fails(*a, **kw):
        raise RuntimeError("Failed to download after 3 attempts")

    def fake_broker(ts, collectors, matcher, full_feed_min, out_path, elems=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.touch()

    monkeypatch.setattr(ribs, "process_snapshot_direct", direct_always_fails)
    monkeypatch.setattr(ribs, "process_snapshot", fake_broker)
    monkeypatch.setattr(ribs, "retry_transport", lambda fn, **kw: fn())

    ribs.run_ribs(_cfg(), tmp_path, {"IR": ["10.0.0.0/8"]}, 0, 24 * 3600,
                  rv_cache_dir=tmp_path / "cache")

    assert (tmp_path / "rib_0.parquet").exists()
    assert (tmp_path / "rib_28800.parquet").exists()
    assert (tmp_path / "rib_57600.parquet").exists()
