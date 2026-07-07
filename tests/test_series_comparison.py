"""D-012 two-series robustness exhibit: unit tests with small fixtures."""

import pandas as pd
import pytest

from src.analysis import series_comparison as sc


def _series(rows):
    return pd.DataFrame(
        rows, columns=["ts", "prefix", "cc", "family", "visibility", "peers_total"]
    )


def test_restricts_to_overlapping_ts_only():
    primary = _series([
        (1000, "a", "IR", 4, 0.9, 100),
        (2000, "b", "IR", 4, 0.9, 100),  # not in ris -> excluded
    ])
    ris = _series([
        (1000, "a", "IR", 4, 0.95, 100),
    ])
    result = sc.visibility_distribution_comparison(primary, ris, min_fullfeed_peers=15)
    assert set(result["ts"]) == {1000}
    assert len(result) == 2  # one row per series at ts=1000


def test_degraded_snapshot_drops_the_whole_shared_ts_not_just_one_side():
    # If primary is degraded at ts=1000, that moment isn't a valid PAIRED
    # comparison point even though ris's own value there is fine - both
    # sides must drop it, not just the degraded one, since the whole point
    # is comparing both series at the same trustworthy snapshot.
    primary = _series([
        (1000, "a", "IR", 4, 0.9, 5),  # degraded, peers_total < 15
    ])
    ris = _series([
        (1000, "a", "IR", 4, 0.95, 100),
    ])
    result = sc.visibility_distribution_comparison(primary, ris, min_fullfeed_peers=15)
    assert len(result) == 0


def test_restricts_to_cc():
    primary = _series([
        (1000, "a", "IR", 4, 0.9, 100),
        (1000, "b", "TR", 4, 0.1, 100),
    ])
    ris = _series([
        (1000, "a", "IR", 4, 0.95, 100),
    ])
    result = sc.visibility_distribution_comparison(primary, ris, min_fullfeed_peers=15)
    assert set(result["prefix"]) == {"a"}


def test_bimodality_summary_separates_ambiguous_from_extreme():
    comparison = pd.DataFrame([
        {"visibility": 0.95, "series": "primary"},
        {"visibility": 0.02, "series": "primary"},
        {"visibility": 0.5, "series": "primary"},   # ambiguous
        {"visibility": 0.99, "series": "ris"},
        {"visibility": 0.01, "series": "ris"},
    ])
    summary = sc.bimodality_summary(comparison).set_index("series")
    assert summary.loc["primary", "n"] == 3
    assert summary.loc["primary", "ambiguous_share"] == pytest.approx(1 / 3)
    assert summary.loc["ris", "ambiguous_share"] == pytest.approx(0.0)
    assert summary.loc["ris", "near_one_share"] == pytest.approx(0.5)
