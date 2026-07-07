"""D-023: unit tests for per-block restoration timing (H3 centerpiece)."""

import pandas as pd
import pytest

from src.analysis import joins


def _vis(rows):
    return pd.DataFrame(rows, columns=["ts", "prefix", "origin_asn", "visibility"])


def _blocks(rows):
    return pd.DataFrame(rows, columns=["prefix", "family"])


_THRESHOLDS = [0.25, 0.5, 0.8]


def test_restoration_ts_is_first_post_p4_crossing_of_primary_threshold(tmp_path):
    # P0 baseline mean = 1.0 (fully visible /16). Blackout at ts=300 (no rows
    # -> visibility 0). P4 starts at ts=400: a /17 (half the /16's space)
    # comes back at ts=400 (weighted 0.5 = exactly 50% of baseline), the
    # full /16 at ts=500 (weighted 1.0).
    vis = _vis([
        (0, "5.22.0.0/16", 49666, 1.0),
        (100, "5.22.0.0/16", 49666, 1.0),
        (200, "5.22.0.0/16", 49666, 1.0),
        (400, "5.22.0.0/17", 49666, 1.0),
        (500, "5.22.0.0/16", 49666, 1.0),
    ])
    blocks = _blocks([("5.22.0.0/16", 4)])
    result = joins.restoration_events(
        vis, blocks,
        p0_start=0, p0_end=300, p4_start=400, steady_state_start=500,
        thresholds=_THRESHOLDS, primary_threshold=0.5,
        out_path=tmp_path / "restoration.parquet",
    )
    row = result.iloc[0]
    assert row.p0_baseline_mean == pytest.approx(1.0)
    assert row.restoration_ts_p50 == 400  # 0.5 >= 0.5 * 1.0
    assert row.restoration_ts_p80 == 500  # only the full /16 clears 0.8
    assert row.restoration_ts == row.restoration_ts_p50  # primary = the 50% column
    assert row.asn == 49666


def test_never_crosses_threshold_is_none(tmp_path):
    vis = _vis([
        (0, "5.22.0.0/16", 1, 1.0),
        (400, "5.22.0.0/24", 1, 1.0),  # only 1/256th ever comes back
    ])
    blocks = _blocks([("5.22.0.0/16", 4)])
    result = joins.restoration_events(
        vis, blocks,
        p0_start=0, p0_end=300, p4_start=400, steady_state_start=400,
        thresholds=_THRESHOLDS, primary_threshold=0.5,
        out_path=tmp_path / "restoration.parquet",
    )
    row = result.iloc[0]
    assert row.restoration_ts_p25 is None
    assert row.restoration_ts_p50 is None
    assert row.restoration_ts_p80 is None


def test_zero_p0_baseline_yields_no_restoration_timing(tmp_path):
    # Block never observed during P0 (e.g. unused allocation) -> no baseline
    # to cross relative to; must not divide by zero or fabricate a crossing.
    vis = _vis([(400, "5.22.0.0/16", 1, 1.0)])
    blocks = _blocks([("5.22.0.0/16", 4)])
    result = joins.restoration_events(
        vis, blocks,
        p0_start=0, p0_end=300, p4_start=400, steady_state_start=400,
        thresholds=_THRESHOLDS, primary_threshold=0.5,
        out_path=tmp_path / "restoration.parquet",
    )
    row = result.iloc[0]
    assert row.p0_baseline_mean is None  # never observed in P0 -> no baseline, not a confirmed zero
    assert row.restoration_ts is None
    assert row.steady_state_ratio is None


def test_steady_state_completeness_is_separate_from_timing(tmp_path):
    # Fully restored by ts=400 but decays afterward: restoration_ts still
    # fires at 400, while steady_state_ratio reflects the later, lower level
    # - timing and completeness must not collapse into one number (D-023).
    vis = _vis([
        (0, "5.22.0.0/16", 1, 1.0),
        (100, "5.22.0.0/16", 1, 1.0),
        (400, "5.22.0.0/16", 1, 1.0),
        (900, "5.22.0.0/24", 1, 1.0),  # steady state: only a sliver remains
    ])
    blocks = _blocks([("5.22.0.0/16", 4)])
    result = joins.restoration_events(
        vis, blocks,
        p0_start=0, p0_end=300, p4_start=400, steady_state_start=900,
        thresholds=_THRESHOLDS, primary_threshold=0.5,
        out_path=tmp_path / "restoration.parquet",
    )
    row = result.iloc[0]
    assert row.restoration_ts == 400
    assert row.steady_state_visibility == pytest.approx(1 / 256)
    assert row.steady_state_ratio == pytest.approx(1 / 256)
