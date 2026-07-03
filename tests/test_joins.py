"""Unit tests for Stage 5 joins with small in-memory fixtures (no network)."""

import pandas as pd

from src.analysis import joins


def _vis(rows):
    return pd.DataFrame(
        rows,
        columns=["ts", "prefix", "family", "origin_asn", "peers_seen",
                 "peers_total", "visibility", "upstreams"],
    )


_ADEQUACY = {"min_nonzero_share": 0.5, "min_median": 5}


def _baseline_parquet(directory, asn, values):
    """Write a baseline-window IODA parquet for one ASN (D-013 fixture)."""
    directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "ts": range(len(values)),
        "entity_type": "asn",
        "entity_code": str(asn),
        "datasource": "ping-slash24",
        "value": values,
    }).to_parquet(directory / f"{asn}.parquet", index=False)


def test_bgp_vs_ioda_gap_becomes_withdrawn(tmp_path):
    # AS 49666 has no rows at ts=2000: fully withdrawn ASes vanish from RIBs,
    # and that absence must surface as the `withdrawn` state, not a missing row.
    vis = _vis([
        (1000, "5.22.192.0/18", 4, 49666, 90, 100, 0.90, "3356"),
        (1000, "91.98.0.0/15", 4, 12880, 95, 100, 0.95, "6762"),
        (2000, "91.98.0.0/15", 4, 12880, 94, 100, 0.94, "6762"),
    ])
    result = joins.bgp_vs_ioda(
        vis, tmp_path / "no_ioda", tmp_path / "no_baseline",
        visibility_announced_min=0.5, probing_dark_ratio=0.2,
        probing_adequacy=_ADEQUACY,
        out_path=tmp_path / "bvi.parquet",
    )
    gap = result[(result.asn == 49666) & (result.ts == 2000)]
    assert len(gap) == 1
    assert gap.state.iloc[0] == "withdrawn"
    ok = result[(result.asn == 12880) & (result.ts == 2000)]
    assert ok.state.iloc[0] == "announced_and_reachable"
    # no baseline data at all -> nobody is probing-adequate
    assert not result.probing_adequate.any()


def test_bgp_vs_ioda_dark_state_with_adequate_baseline(tmp_path):
    # AS stays announced while probing collapses to 1 against a baseline of 100:
    # with an adequate baseline this must surface as announced_but_dark.
    vis = _vis([
        (1000, "91.98.0.0/15", 4, 12880, 95, 100, 0.95, "6762"),
        (2000, "91.98.0.0/15", 4, 12880, 94, 100, 0.94, "6762"),
    ])
    ioda_dir = tmp_path / "ioda"
    ioda_dir.mkdir()
    pd.DataFrame({
        "ts": [1000, 2000],
        "entity_type": "asn",
        "entity_code": "12880",
        "datasource": "ping-slash24",
        "value": [100.0, 1.0],
    }).to_parquet(ioda_dir / "12880.parquet", index=False)
    _baseline_parquet(tmp_path / "baseline", 12880, [100.0] * 10)

    result = joins.bgp_vs_ioda(
        vis, ioda_dir, tmp_path / "baseline",
        visibility_announced_min=0.5, probing_dark_ratio=0.2,
        probing_adequacy=_ADEQUACY,
        out_path=tmp_path / "bvi.parquet",
    )
    assert result.probing_adequate.all()
    assert result[result.ts == 1000].state.iloc[0] == "announced_and_reachable"
    assert result[result.ts == 2000].state.iloc[0] == "announced_but_dark"


def test_bgp_vs_ioda_inadequate_baseline_excluded(tmp_path):
    # Baseline mostly zeros -> fails the D-013 adequacy rule -> no dark calls,
    # AS lands on the published exclusion list.
    vis = _vis([
        (1000, "91.98.0.0/15", 4, 12880, 95, 100, 0.95, "6762"),
    ])
    _baseline_parquet(tmp_path / "baseline", 12880, [0.0] * 9 + [100.0])

    excl_path = tmp_path / "excluded.csv"
    result = joins.bgp_vs_ioda(
        vis, tmp_path / "no_ioda", tmp_path / "baseline",
        visibility_announced_min=0.5, probing_dark_ratio=0.2,
        probing_adequacy=_ADEQUACY,
        out_path=tmp_path / "bvi.parquet",
        excluded_out_path=excl_path,
    )
    assert not result.probing_adequate.any()
    excluded = pd.read_csv(excl_path)
    assert list(excluded.asn) == [12880]


def test_upstream_transitions_flags_change(tmp_path):
    vis = _vis([
        (1000, "5.22.192.0/18", 4, 49666, 90, 100, 0.90, "3356,1299"),
        (2000, "5.22.192.0/18", 4, 49666, 50, 100, 0.50, "3356"),
    ])
    result = joins.upstream_transitions(vis, tmp_path / "ut.parquet")
    assert list(result.changed) == [False, True]
    assert list(result.n_upstreams) == [2, 1]


def test_event_speed_uses_first_withdrawal_per_prefix(tmp_path):
    events = pd.DataFrame([
        dict(ts=100, prefix="a", asn=1, event="withdraw", peer_asn=2, as_path=""),
        dict(ts=500, prefix="a", asn=1, event="withdraw", peer_asn=3, as_path=""),  # dup, later
        dict(ts=160, prefix="b", asn=1, event="withdraw", peer_asn=2, as_path=""),
        dict(ts=150, prefix="a", asn=1, event="announce", peer_asn=2, as_path="2 1"),
    ])
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    events.to_parquet(events_dir / "w1.parquet", index=False)
    result = joins.event_speed(events_dir, tmp_path / "es.parquet")
    assert result.n_prefixes_withdrawn.iloc[0] == 2
    assert result.duration_s.iloc[0] == 60  # 160 - 100, dup withdrawal ignored
