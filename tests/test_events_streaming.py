"""process_window flushes event batches to disk instead of holding the window in RAM."""

from types import SimpleNamespace

import pandas as pd
import pyarrow.parquet as pq
import pytest

from src.bgp import events as events_mod
from src.bgp.events import _iter_direct_ris, process_window, process_window_direct, run_events
from src.common.prefixmatch import PrefixMatcher


def _elem(t, etype, prefix, as_path="", peer="10.0.0.1", peer_asn=64500):
    fields = {"prefix": prefix}
    if etype == "A":
        fields["as-path"] = as_path
    return SimpleNamespace(type=etype, fields=fields, time=t,
                           peer_address=peer, peer_asn=peer_asn)


@pytest.fixture
def matcher():
    return PrefixMatcher({"IR": ["5.22.200.0/24"], "TR": ["78.170.0.0/16"]})


def _window():
    return SimpleNamespace(name="w1", start=0, end=100)


def test_streams_multiple_row_groups_and_preserves_content(tmp_path, matcher):
    elems = [
        _elem(1, "A", "5.22.200.0/24", "3356 12880"),
        _elem(2, "A", "78.170.1.0/24", "3356 9121"),
        _elem(3, "W", "5.22.200.0/24"),
        _elem(4, "A", "8.8.8.0/24", "15169"),  # unmatched, dropped
        _elem(5, "W", "78.170.1.0/24"),
    ]
    out = tmp_path / "w1.parquet"
    process_window(_window(), [], matcher, out, elems=elems, flush_rows=2)

    assert pq.ParquetFile(out).num_row_groups == 2  # 2 + 2 rows
    df = pd.read_parquet(out)
    assert df["ts"].tolist() == [1, 2, 3, 5]
    assert df["event"].tolist() == ["announce", "announce", "withdraw", "withdraw"]
    # withdraw origin comes from the last announce of the same peer+prefix
    assert df.loc[2, "asn"] == 12880
    assert df["cc"].tolist() == ["IR", "TR", "IR", "TR"]


def test_failure_mid_stream_leaves_no_files(tmp_path, matcher):
    def elems():
        yield _elem(1, "A", "5.22.200.0/24", "3356 12880")
        raise RuntimeError("transport died")

    out = tmp_path / "w1.parquet"
    with pytest.raises(RuntimeError, match="transport died"):
        process_window(_window(), [], matcher, out, elems=elems(), flush_rows=1)
    assert not out.exists()
    assert not out.with_suffix(".parquet.tmp").exists()


def test_empty_window_writes_empty_file(tmp_path, matcher):
    out = tmp_path / "w1.parquet"
    process_window(_window(), [], matcher, out, elems=[])
    df = pd.read_parquet(out)
    assert len(df) == 0
    assert list(df.columns) == ["ts", "prefix", "cc", "asn", "event", "peer_asn", "as_path"]


class TestProcessWindowDirect:
    """D-021: RIS collectors fetch update dumps directly; RouteViews stays on broker."""

    def test_merges_direct_ris_files_and_broker_stream(self, tmp_path, matcher, monkeypatch):
        fetched: list[tuple[str, int]] = []

        def fake_fetch_update(base, collector, ts, cache_dir):
            fetched.append((collector, ts))
            p = tmp_path / f"raw_{collector}_{ts}"
            p.write_bytes(b"fake dump")
            return p

        def fake_read_update_file(path, collector):
            _, coll, ts = path.name.split("_")
            yield _elem(int(ts), "A", "5.22.200.0/24", "3356 12880", peer=f"{coll}-peer")

        monkeypatch.setattr("src.bgp.risfiles.fetch_update", fake_fetch_update)
        monkeypatch.setattr("src.bgp.risfiles.read_update_file", fake_read_update_file)
        monkeypatch.setattr(
            events_mod, "open_stream",
            lambda start, end, collectors, record_type: iter(
                [_elem(500, "W", "5.22.200.0/24", peer="rv-peer")]
            ),
        )

        out = tmp_path / "w1.parquet"
        window = SimpleNamespace(name="w1", start=0, end=600)
        process_window_direct(
            window, ["rrc00"], ["route-views2"], matcher, out,
            "https://data.ris.ripe.net", tmp_path, ["rrc00", "route-views2"],
        )

        df = pd.read_parquet(out)
        # 2 direct-fetched RIS files (ts=0, 300 on the 5-min grid within
        # [0,600)) each yield one announce; the broker-backed RouteViews
        # stream contributes the one withdraw.
        assert sorted(df["event"]) == ["announce", "announce", "withdraw"]
        assert len(fetched) == 2  # direct-fetch path actually ran, one file per grid step
        # fetched raw files are cleaned up as soon as each is replayed
        assert not list(tmp_path.glob("raw_*"))

    def test_prefetch_concurrency_preserves_chronological_replay(self, tmp_path, monkeypatch):
        # Downloads complete out of submission order (later ts finishes
        # first); replay must still come out in ts order per collector.
        import time

        def fake_fetch_update(base, collector, ts, cache_dir):
            time.sleep(0.02 if ts == 0 else 0.001)
            p = tmp_path / f"raw_{collector}_{ts}"
            p.write_bytes(b"x")
            return p

        def fake_read_update_file(path, collector):
            _, coll, ts = path.name.split("_")
            yield SimpleNamespace(marker=int(ts))

        monkeypatch.setattr("src.bgp.risfiles.fetch_update", fake_fetch_update)
        monkeypatch.setattr("src.bgp.risfiles.read_update_file", fake_read_update_file)

        elems = list(_iter_direct_ris(
            ["rrc00"], "https://data.ris.ripe.net", 0, 1500, tmp_path, max_workers=4,
        ))
        assert [e.marker for e in elems] == [0, 300, 600, 900, 1200]

    def test_bounded_disk_usage_when_fetch_outpaces_replay(self, tmp_path, monkeypatch):
        # Reproduces the 2026-07-06 EC2 incident: fetch (fast I/O) racing
        # ahead of replay (slower) must not let unconsumed files pile up
        # past max_workers, or a long window fills the disk.
        import time

        max_outstanding = {"n": 0}

        def fake_fetch_update(base, collector, ts, cache_dir):
            n = len(list(tmp_path.glob("raw_*")))
            max_outstanding["n"] = max(max_outstanding["n"], n)
            p = tmp_path / f"raw_{collector}_{ts}"
            p.write_bytes(b"x")
            return p

        def fake_read_update_file(path, collector):
            time.sleep(0.005)  # replay slower than the (instant) fake fetch
            yield SimpleNamespace(marker=1)

        monkeypatch.setattr("src.bgp.risfiles.fetch_update", fake_fetch_update)
        monkeypatch.setattr("src.bgp.risfiles.read_update_file", fake_read_update_file)

        max_workers = 4
        list(_iter_direct_ris(
            ["rrc00"], "https://data.ris.ripe.net", 0, 30 * 300, tmp_path,
            max_workers=max_workers,
        ))
        assert max_outstanding["n"] <= max_workers

    def test_keep_files_true_retains_fetched_dumps(self, tmp_path, matcher, monkeypatch):
        def fake_fetch_update(base, collector, ts, cache_dir):
            p = tmp_path / f"raw_{collector}_{ts}"
            p.write_bytes(b"fake dump")
            return p

        monkeypatch.setattr("src.bgp.risfiles.fetch_update", fake_fetch_update)
        monkeypatch.setattr("src.bgp.risfiles.read_update_file", lambda path, collector: iter([]))
        monkeypatch.setattr(events_mod, "open_stream", lambda *a, **kw: iter([]))

        out = tmp_path / "w1.parquet"
        window = SimpleNamespace(name="w1", start=0, end=300)
        process_window_direct(
            window, ["rrc00"], [], matcher, out,
            "https://data.ris.ripe.net", tmp_path, ["rrc00"], keep_files=True,
        )
        assert list(tmp_path.glob("raw_*"))


class TestRunEventsFallback:
    """D-021: a direct-fetch failure falls back to the D-017-era broker path."""

    def test_direct_failure_falls_back_to_broker(self, tmp_path, matcher, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("Failed to download updates dump after 3 attempts")

        broker_calls: list[list[str]] = []

        def fake_process_window(window, collectors, matcher, out_path, elems=None, flush_rows=None):
            broker_calls.append(collectors)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"")

        monkeypatch.setattr(events_mod, "process_window_direct", boom)
        monkeypatch.setattr(events_mod, "process_window", fake_process_window)

        cfg = SimpleNamespace(collectors=["rrc00", "route-views2"], ris_backfill_collectors=["rrc00"])
        window = SimpleNamespace(name="w1", start=0, end=300)
        events_dir = tmp_path / "events"
        run_events(
            cfg, events_dir, {"IR": ["5.22.200.0/24"]}, [window],
            ris_base="https://data.ris.ripe.net", ris_cache_dir=tmp_path,
        )

        assert broker_calls == [["rrc00", "route-views2"]]
        assert (events_dir / "w1.parquet").exists()

    def test_no_ris_base_skips_direct_path_entirely(self, tmp_path, monkeypatch):
        called = {"direct": False}

        def fail_if_called(*a, **kw):
            called["direct"] = True
            raise AssertionError("direct path should not run without ris_base")

        broker_calls: list[list[str]] = []

        def fake_process_window(window, collectors, matcher, out_path, elems=None, flush_rows=None):
            broker_calls.append(collectors)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"")

        monkeypatch.setattr(events_mod, "process_window_direct", fail_if_called)
        monkeypatch.setattr(events_mod, "process_window", fake_process_window)

        cfg = SimpleNamespace(collectors=["rrc00"], ris_backfill_collectors=["rrc00"])
        window = SimpleNamespace(name="w1", start=0, end=300)
        events_dir = tmp_path / "events"
        run_events(cfg, events_dir, {"IR": ["5.22.200.0/24"]}, [window])

        assert not called["direct"]
        assert broker_calls == [["rrc00"]]
