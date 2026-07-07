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


def test_event_speed_flap_threshold_skips_quick_reannouncement(tmp_path):
    # Same peer session withdraws prefix "a" at ts=100 then reannounces it
    # just 50s later (peer_asn=2 both times) - a flap under T=60s (D-009).
    # The prefix's first REAL withdrawal is the later one at ts=300.
    events = pd.DataFrame([
        dict(ts=100, prefix="a", cc="IR", asn=1, event="withdraw", peer_asn=2, as_path=""),
        dict(ts=150, prefix="a", cc="IR", asn=1, event="announce", peer_asn=2, as_path="2 1"),
        dict(ts=300, prefix="a", cc="IR", asn=1, event="withdraw", peer_asn=2, as_path=""),
        dict(ts=360, prefix="b", cc="IR", asn=1, event="withdraw", peer_asn=2, as_path=""),
    ])
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    events.to_parquet(events_dir / "w1.parquet", index=False)

    unfiltered = joins.event_speed(events_dir, tmp_path / "es_unfiltered.parquet")
    assert unfiltered.t_first.iloc[0] == 100  # flap withdrawal counts without filtering

    filtered = joins.event_speed(
        events_dir, tmp_path / "es_filtered.parquet", flap_threshold_s=60
    )
    assert filtered.t_first.iloc[0] == 300  # flap at ts=100 excluded; real withdrawal wins


def test_fine_restoration_order_uses_first_announce_per_block(tmp_path):
    events = pd.DataFrame([
        # block 5.22.0.0/16: two prefixes inside it reannounce at different times
        dict(ts=1000, prefix="5.22.1.0/24", cc="IR", asn=1, event="announce", peer_asn=2, as_path=""),
        dict(ts=1500, prefix="5.22.2.0/24", cc="IR", asn=1, event="announce", peer_asn=2, as_path=""),
        dict(ts=900, prefix="5.22.1.0/24", cc="IR", asn=1, event="withdraw", peer_asn=2, as_path=""),
        # control-country row must not leak into an IR block's timing
        dict(ts=1, prefix="5.22.3.0/24", cc="TR", asn=9, event="announce", peer_asn=2, as_path=""),
    ])
    blocks = pd.DataFrame([("5.22.0.0/16", 4)], columns=["prefix", "family"])
    result = joins.fine_restoration_order(events, blocks, since_ts=0, out_path=tmp_path / "fro.parquet")
    row = result.iloc[0]
    assert row.prefix == "5.22.0.0/16"
    assert row.first_reannounce_ts == 1000  # earliest announce, not the withdraw or the TR row


def test_fine_restoration_order_ignores_activity_before_since_ts(tmp_path):
    # The pulled event window has pre-boundary margin - an announce that
    # happened before since_ts (the P4 boundary) is ordinary pre-restoration
    # routing activity, not the restoration itself, and must not win the min().
    events = pd.DataFrame([
        dict(ts=100, prefix="5.22.1.0/24", cc="IR", asn=1, event="announce", peer_asn=2, as_path=""),
        dict(ts=2000, prefix="5.22.2.0/24", cc="IR", asn=1, event="announce", peer_asn=2, as_path=""),
    ])
    blocks = pd.DataFrame([("5.22.0.0/16", 4)], columns=["prefix", "family"])
    result = joins.fine_restoration_order(
        events, blocks, since_ts=1000, out_path=tmp_path / "fro2.parquet"
    )
    row = result.iloc[0]
    assert row.first_reannounce_ts == 2000  # the ts=100 row is before since_ts, excluded


def test_restoration_order_by_type_joins_asn_to_classification(tmp_path):
    fine_order = pd.DataFrame([
        {"prefix": "5.22.0.0/16", "first_reannounce_ts": 1100},
        {"prefix": "8.8.0.0/16", "first_reannounce_ts": 2000},
    ])
    restoration = pd.DataFrame([
        {"prefix": "5.22.0.0/16", "asn": 1},
        {"prefix": "8.8.0.0/16", "asn": 2},
    ])
    classification = pd.DataFrame([
        {"asn": 1, "type": "state_gateway"},
        {"asn": 2, "type": "consumer_isp"},
    ])
    result = joins.restoration_order_by_type(
        fine_order, restoration, classification, window_start=1000,
        out_path=tmp_path / "robt.parquet",
    )
    result = result.set_index("type")
    assert result.loc["state_gateway", "median_delay_s"] == 100
    assert result.loc["consumer_isp", "median_delay_s"] == 1000


def test_restoration_by_type_keeps_never_restored_visible(tmp_path):
    # A block from a never-restored ASN must count toward n_never_restored,
    # not be silently dropped out of the aggregate (dropping it would bias
    # median_delay_s toward only the ASNs that did recover - exactly the H3
    # selectivity question this table exists to answer).
    restoration = pd.DataFrame([
        {"prefix": "5.22.0.0/16", "asn": 1, "restoration_ts": 1500,
         "steady_state_ratio": 1.0},
        {"prefix": "8.8.0.0/16", "asn": 2, "restoration_ts": None,
         "steady_state_ratio": 0.01},
    ])
    classification = pd.DataFrame([
        {"asn": 1, "type": "state_gateway"},
        {"asn": 2, "type": "consumer_isp"},
    ])
    result = joins.restoration_by_type(
        restoration, classification, p4_start=1000, out_path=tmp_path / "rbt.parquet"
    )
    result = result.set_index("type")
    assert result.loc["state_gateway", "n_restored"] == 1
    assert result.loc["state_gateway", "median_delay_s"] == 500
    assert result.loc["consumer_isp", "n_never_restored"] == 1
    assert result.loc["consumer_isp", "n_restored"] == 0


def test_event_speed_interpercentile_range_ignores_stragglers(tmp_path):
    """D-024: duration_p5_p95_s (t_p95 - t_p5) must not be swung by a single
    straggler prefix the way the full range (duration_s) is."""
    prefixes_at = {f"p{i}": 1000 + i for i in range(20)}  # tight cluster, 1000..1019
    prefixes_at["straggler"] = 100000  # one very late outlier
    events = pd.DataFrame([
        dict(ts=ts, prefix=p, asn=1, event="withdraw", peer_asn=2, as_path="")
        for p, ts in prefixes_at.items()
    ])
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    events.to_parquet(events_dir / "w1.parquet", index=False)
    result = joins.event_speed(events_dir, tmp_path / "es.parquet")
    row = result.iloc[0]
    assert row.duration_s > 90000  # full range dominated by the straggler
    assert row.duration_p5_p95_s < 100  # interpercentile range stays within the tight cluster
