"""D-025 robustness: unit tests for the parameterized per-phase breakdown."""

import pandas as pd
import pytest

from src.common.config import Window
from src.analysis import phase_breakdown as pb


def _phases(bounds):
    return {name: Window(name=name, start=s, end=e) for name, (s, e) in bounds.items()}


def test_dark_and_withdrawn_share_buckets_by_phase():
    df = pd.DataFrame([
        {"ts": 0, "asn": 1, "state": "announced_and_reachable"},
        {"ts": 0, "asn": 2, "state": "announced_but_dark"},
        {"ts": 100, "asn": 1, "state": "withdrawn"},
        {"ts": 100, "asn": 2, "state": "announced_but_dark"},
        {"ts": 200, "asn": 1, "state": "announced_and_reachable"},  # outside every phase
    ])
    phases = _phases({"P0": (0, 100), "P1": (100, 200)})
    result = pb.dark_and_withdrawn_share(df, phases)
    assert result.loc["P0", "dark_share"] == pytest.approx(0.5)
    assert result.loc["P0", "n"] == 2
    assert result.loc["P1", "dark_share"] == pytest.approx(0.5)
    assert result.loc["P1", "withdrawn_share"] == pytest.approx(0.5)


def test_transition_rate_by_phase():
    df = pd.DataFrame([
        {"ts": 0, "asn": 1, "changed": False},
        {"ts": 0, "asn": 2, "changed": True},
        {"ts": 100, "asn": 1, "changed": True},
    ])
    phases = _phases({"P0": (0, 100), "P1": (100, 200)})
    result = pb.transition_rate_by_phase(df, phases)
    assert result.loc["P0", "transition_rate"] == pytest.approx(0.5)
    assert result.loc["P1", "transition_rate"] == pytest.approx(1.0)


def test_visibility_by_type_by_phase_uses_mean_of_means():
    # Two ts in P0 with different n_prefixes should NOT be prefix-count-weighted -
    # this must be a plain mean of the per-ts-per-type means already in the input.
    df = pd.DataFrame([
        {"ts": 0, "type": "isp", "visibility_mean": 1.0, "n_prefixes": 1},
        {"ts": 50, "type": "isp", "visibility_mean": 0.0, "n_prefixes": 1000},
    ])
    phases = _phases({"P0": (0, 100)})
    result = pb.visibility_by_type_by_phase(df, phases)
    assert result.loc["P0", "isp"] == pytest.approx(0.5)  # not 0.001 (prefix-weighted)


def test_shifted_phases_keeps_boundaries_contiguous():
    phases = _phases({"P0": (0, 100), "P1": (100, 200), "P2": (200, 300)})
    shifted = pb.shifted_phases(phases, "P1", shift_seconds=10)
    assert shifted["P1"].end == 210
    assert shifted["P2"].start == 210
    # untouched boundaries stay fixed
    assert shifted["P0"].end == 100
    assert shifted["P2"].end == 300


def test_shifted_phases_negative_shift():
    phases = _phases({"P0": (0, 100), "P1": (100, 200), "P2": (200, 300)})
    shifted = pb.shifted_phases(phases, "P1", shift_seconds=-10)
    assert shifted["P1"].end == 190
    assert shifted["P2"].start == 190


def test_shifted_phases_rejects_last_phase():
    phases = _phases({"P0": (0, 100), "P1": (100, 200)})
    with pytest.raises(ValueError, match="no following phase"):
        pb.shifted_phases(phases, "P1", shift_seconds=10)


def test_boundary_sensitivity_sweep_reports_each_shift_and_handles_emptied_phase():
    bvi = pd.DataFrame([
        {"ts": 50, "asn": 1, "state": "announced_but_dark"},
        {"ts": 150, "asn": 1, "state": "announced_but_dark"},
        {"ts": 150, "asn": 2, "state": "announced_and_reachable"},
        {"ts": 250, "asn": 1, "state": "announced_and_reachable"},
    ])
    ut = pd.DataFrame([
        {"ts": 50, "asn": 1, "changed": False},
        {"ts": 150, "asn": 1, "changed": True},
        {"ts": 250, "asn": 1, "changed": False},
    ])
    # P2 is only 100s wide (100..200) - narrower than a 150s shift, so a +150s
    # shift should empty it out entirely, same structural break found on the
    # real P1/P2 boundary at +24h.
    phases = _phases({"P0": (0, 100), "P1": (100, 200), "P2": (200, 300)})
    result = pb.boundary_sensitivity_sweep(
        bvi, ut, phases, boundary="P1", shifts_seconds=[-50, 0, 150]
    ).set_index("shift_s")

    assert result.loc[0, "P1_dark_share"] == pytest.approx(0.5)  # ts=150: 1 dark, 1 reachable
    assert result.loc[0, "P2_n"] == 1  # ts=250 only
    # +150s pushes P1's end to 350, past P2's own end (300) - P2 vanishes.
    # NaN (no data), not 0, is the correct signal - there's a real
    # difference between "measured zero" and "couldn't measure."
    assert pd.isna(result.loc[150, "P2_n"])
    assert pd.isna(result.loc[150, "P2_dark_share"])


def test_snapshot_trajectory_reports_raw_per_ts_values():
    bvi = pd.DataFrame([
        {"ts": 100, "asn": 1, "state": "announced_and_reachable"},
        {"ts": 100, "asn": 2, "state": "announced_and_reachable"},
        {"ts": 200, "asn": 1, "state": "announced_but_dark"},
        {"ts": 200, "asn": 2, "state": "announced_and_reachable"},
    ])
    result = pb.snapshot_trajectory(bvi, [100, 200, 999]).set_index("ts")
    assert result.loc[100, "dark_share"] == pytest.approx(0.0)
    assert result.loc[200, "dark_share"] == pytest.approx(0.5)
    assert result.loc[999, "n"] == 0  # ts with no rows at all


def test_withdrawal_wave_timing_excludes_pre_boundary_buffer_noise():
    events = pd.DataFrame([
        # pre-boundary buffer-day noise: must not pollute the percentiles
        {"ts": 0, "prefix": "1.0.0.0/24", "asn": 1, "peer_asn": 1, "event": "withdraw", "cc": "IR"},
        {"ts": 5, "prefix": "2.0.0.0/24", "asn": 2, "peer_asn": 1, "event": "withdraw", "cc": "IR"},
        # the real wave, all at/after phase_start=1000
        {"ts": 1000, "prefix": "3.0.0.0/24", "asn": 3, "peer_asn": 1, "event": "withdraw", "cc": "IR"},
        {"ts": 1010, "prefix": "4.0.0.0/24", "asn": 4, "peer_asn": 1, "event": "withdraw", "cc": "IR"},
        {"ts": 1020, "prefix": "5.0.0.0/24", "asn": 5, "peer_asn": 1, "event": "withdraw", "cc": "IR"},
        {"ts": 1030, "prefix": "6.0.0.0/24", "asn": 6, "peer_asn": 1, "event": "withdraw", "cc": "IR"},
    ])
    result = pb.withdrawal_wave_timing(events, phase_start=1000, flap_threshold_s=60)
    assert result["n_prefixes"] == 4
    assert result["t_min"] == 1000
