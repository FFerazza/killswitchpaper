import pandas as pd

from src.analysis.threshold_calibration import (
    find_valley,
    largest_ratio_under,
    p0_visibility_histogram,
)


def _hist(counts):
    n = len(counts)
    edges = [i / n for i in range(n + 1)]
    return pd.DataFrame({"bin_lo": edges[:-1], "bin_hi": edges[1:], "count": counts})


def test_find_valley_locates_empty_run_between_modes():
    # 10 bins over [0,1]: mass near 0 and near 1, a clean empty middle.
    counts = [50, 40, 0, 0, 0, 0, 0, 0, 30, 60]
    valley = find_valley(_hist(counts), search_lo=0.0, search_hi=1.0)
    assert valley["empty_run"] is True
    assert 0.2 <= valley["valley_lo"] < valley["valley_hi"] <= 0.8
    assert valley["valley_lo"] <= valley["candidate_threshold"] <= valley["valley_hi"]


def test_find_valley_falls_back_to_sparsest_bin_when_no_empty_run():
    counts = [50, 40, 5, 3, 4, 6, 3, 5, 30, 60]
    valley = find_valley(_hist(counts), search_lo=0.0, search_hi=1.0)
    assert valley["empty_run"] is False
    assert valley["min_count_in_band"] == 3


def test_largest_ratio_under_picks_max_passing_ratio():
    sweep = pd.DataFrame({
        "ratio": [0.1, 0.2, 0.3, 0.4],
        "false_dark_rate": [0.0, 0.005, 0.02, 0.05],
    })
    assert largest_ratio_under(sweep, max_false_dark_rate=0.01) == 0.2


def test_largest_ratio_under_none_when_all_fail():
    sweep = pd.DataFrame({"ratio": [0.1, 0.2], "false_dark_rate": [0.02, 0.05]})
    assert largest_ratio_under(sweep, max_false_dark_rate=0.01) is None


def test_p0_visibility_histogram_restricts_to_window_and_collapses_per_as():
    visibility = pd.DataFrame({
        "ts": [1, 1, 2, 100],
        "origin_asn": [10, 10, 10, 20],
        "visibility": [0.2, 0.9, 0.9, 0.5],
    })
    hist = p0_visibility_histogram(visibility, p0_start=0, p0_end=10, n_bins=10)
    assert hist["count"].sum() == 2  # ts=1 (max=0.9) and ts=2 (0.9) for asn 10; ts=100 excluded
