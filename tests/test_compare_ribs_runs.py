"""D-016 gate: tagged runs must reproduce pre-D-016 runs exactly on IR rows."""

import pandas as pd

from src.analysis.compare_ribs_runs import compare_snapshot


def _snap(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "ts": 0,
        "family": 4,
        "origin_asn": 65000,
        "peers_seen": 40,
        "peers_total": 50,
        "visibility": 0.8,
        "collector_fullfeed": '{"route-views2": {"ipv4": 50, "ipv6": 29}}',
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def test_identical_ir_rows_pass_even_with_extra_control_rows():
    base = _snap([{"prefix": "10.0.0.0/24"}])  # pre-D-016: no cc column
    cand = _snap([
        {"prefix": "10.0.0.0/24", "cc": "IR"},
        {"prefix": "192.0.2.0/24", "cc": "TR", "visibility": 0.5},
    ])
    assert compare_snapshot(base, cand) == []


def test_numeric_drift_on_ir_rows_is_flagged():
    base = _snap([{"prefix": "10.0.0.0/24"}])
    cand = _snap([{"prefix": "10.0.0.0/24", "cc": "IR", "visibility": 0.7, "peers_seen": 35}])
    problems = compare_snapshot(base, cand)
    assert any("visibility" in p for p in problems)
    assert any("peers_seen" in p for p in problems)


def test_prefix_set_and_audit_differences_are_flagged():
    base = _snap([{"prefix": "10.0.0.0/24"}, {"prefix": "10.0.1.0/24"}])
    cand = _snap([{
        "prefix": "10.0.0.0/24", "cc": "IR",
        "collector_fullfeed": '{"route-views2": {"ipv4": 51, "ipv6": 29}}',
    }])
    problems = compare_snapshot(base, cand)
    assert any("IR prefix sets differ" in p for p in problems)
    assert any("collector_fullfeed differs" in p for p in problems)
