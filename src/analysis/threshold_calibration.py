"""D-013 steps 4-5: candidate final values for the two H1 thresholds left
provisional by D-013 (visibility_announced_min, probing_dark_ratio).

D-013 step 4: place visibility_announced_min in the empty valley between the
two modes of the P0, per-AS visibility distribution.
D-013 step 5: calibrate probing_dark_ratio on the D-008 control population
over a quiet period, choosing the largest ratio whose false-dark rate is
< 1%.

This module only computes candidates. Per CLAUDE.md ("never pick a value
silently"), the values it prints are PROPOSALS for human sign-off, recorded
in DECISIONS.md only after that sign-off (D-026).

Usage:
    python -m src.analysis.threshold_calibration
Output:
    outputs/p0_visibility_histogram.csv
    outputs/dark_ratio_calibration.csv
    a printed summary with the candidate values and the data behind them.
"""

import argparse

import numpy as np
import pandas as pd
import yaml

from src.analysis import joins
from src.analysis.controls import control_dark_rows
from src.analysis.joins import _per_as_visibility
from src.common.config import CONFIG_DIR, DATA_DIR, OUTPUTS_DIR, Config
from src.common.log import get_logger
from src.common.timeutil import snapshot_times

log = get_logger("analysis.threshold_calibration")


def p0_visibility_histogram(
    visibility: pd.DataFrame, p0_start: int, p0_end: int, n_bins: int = 200
) -> pd.DataFrame:
    """Per-AS visibility values (max across an AS's prefixes) within P0,
    binned over [0, 1]."""
    per_as = _per_as_visibility(visibility)
    p0 = per_as[(per_as["ts"] >= p0_start) & (per_as["ts"] < p0_end)]
    counts, edges = np.histogram(p0["visibility"], bins=n_bins, range=(0.0, 1.0))
    return pd.DataFrame({"bin_lo": edges[:-1], "bin_hi": edges[1:], "count": counts})


def find_valley(
    histogram: pd.DataFrame, search_lo: float = 0.05, search_hi: float = 0.95
) -> dict:
    """Widest contiguous run of empty bins strictly between the near-0 and
    near-1 modes, restricted to [search_lo, search_hi] so the search can't
    land in the distribution's own tails. Falls back to the single sparsest
    bin if no bin in the search band is exactly empty.
    """
    band = histogram[
        (histogram["bin_lo"] >= search_lo) & (histogram["bin_hi"] <= search_hi)
    ].reset_index(drop=True)
    zero = band["count"] == 0
    if not zero.any():
        min_count = int(band["count"].min())
        idx = band.index[band["count"] == min_count]
        lo, hi = band.loc[idx.min(), "bin_lo"], band.loc[idx.max(), "bin_hi"]
        return {
            "valley_lo": float(lo), "valley_hi": float(hi),
            "candidate_threshold": float((lo + hi) / 2),
            "empty_run": False, "min_count_in_band": min_count,
        }
    best_start = best_len = cur_start = cur_len = 0
    for i, z in enumerate(zero):
        if z:
            if cur_len == 0:
                cur_start = i
            cur_len += 1
            if cur_len > best_len:
                best_len, best_start = cur_len, cur_start
        else:
            cur_len = 0
    lo = band.loc[best_start, "bin_lo"]
    hi = band.loc[best_start + best_len - 1, "bin_hi"]
    return {
        "valley_lo": float(lo), "valley_hi": float(hi),
        "candidate_threshold": float((lo + hi) / 2),
        "empty_run": True, "min_count_in_band": 0,
    }


def dark_ratio_false_positive_sweep(
    control_asns: dict, ioda_asn_dir, baseline_dir, grid: list[int],
    ratios: list[float], probing_adequacy: dict,
) -> pd.DataFrame:
    """For each candidate ratio: false-dark rate = share of (control ASN, ts)
    pairs over the full grid that would be misclassified announced_but_dark.
    Reuses the same per-pair machinery as the D-014 artifact check, pooled
    across the whole grid rather than reported per bin.
    """
    rows = []
    for ratio in ratios:
        per_asn = control_dark_rows(
            control_asns, ioda_asn_dir, baseline_dir, grid, ratio, probing_adequacy,
        )
        rows.append({
            "ratio": ratio,
            "n_pairs": len(per_asn),
            "n_controls": int(per_asn["asn"].nunique()),
            "false_dark_rate": float(per_asn["dark"].mean()),
        })
    return pd.DataFrame(rows)


def largest_ratio_under(sweep: pd.DataFrame, max_false_dark_rate: float = 0.01) -> float | None:
    ok = sweep[sweep["false_dark_rate"] < max_false_dark_rate]
    if ok.empty:
        return None
    return float(ok["ratio"].max())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config-dir", default=CONFIG_DIR)
    args = ap.parse_args()

    cfg = Config.load(args.config_dir)
    p0 = cfg.phase_window("P0")

    vis_path = DATA_DIR / "bgp" / "visibility_timeseries.parquet"
    if not vis_path.exists():
        raise SystemExit(f"{vis_path} not found - run the primary ribs pipeline first")
    visibility = pd.read_parquet(vis_path)
    if "cc" not in visibility.columns:
        visibility["cc"] = "IR"
    visibility = joins.drop_degraded(visibility, int(cfg.analysis["min_fullfeed_peers"]))
    visibility = visibility[visibility["cc"] == "IR"].reset_index(drop=True)

    hist = p0_visibility_histogram(visibility, p0.start, p0.end)
    hist.to_csv(OUTPUTS_DIR / "p0_visibility_histogram.csv", index=False)
    valley = find_valley(hist)
    pd.DataFrame([valley]).to_csv(OUTPUTS_DIR / "p0_visibility_valley_summary.csv", index=False)
    log.info("P0 per-AS visibility valley: [%.4f, %.4f], candidate threshold=%.4f "
              "(empty_run=%s, min_count_in_band=%d)",
              valley["valley_lo"], valley["valley_hi"], valley["candidate_threshold"],
              valley["empty_run"], valley["min_count_in_band"])

    controls_path = CONFIG_DIR / "controls.yaml"
    if not controls_path.exists():
        raise SystemExit(f"{controls_path} not found - run python -m src.population.controls")
    with open(controls_path) as f:
        controls = yaml.safe_load(f)

    # D-008's control population has no documented nationwide shutdown for
    # its whole selection window (config/controls.yaml caveats: [] - no
    # exclusions recorded), so "quiet periods" for calibration purposes is
    # the full study period, not just P0: a P0-only sweep passed ratio=0.8
    # at <1% false-dark, but that value FAILED the existing D-008 bin-level
    # artifact gate badly when checked over the full period (176/1278 bins
    # flagged, some control ASNs hitting 50% dark share) - a handful of
    # low-baseline control ASNs (AE 41268/8966/216071, PK 59257/59605/38710)
    # are noisy enough that a permissive ratio false-triggers on them
    # outside the P0 window. Calibrating on the full period the ratio will
    # actually be applied over is the robust choice; a P0-only calibration
    # would have been an overfit to one slice of the control data.
    sp = cfg.study_period
    grid = list(snapshot_times(sp.start, sp.end, cfg.rib_interval_hours))
    ratios = [round(r, 2) for r in np.arange(0.05, 1.0, 0.05)]
    sweep = dark_ratio_false_positive_sweep(
        controls["asns"], DATA_DIR / "ioda" / "asn", DATA_DIR / "ioda" / "baseline" / "asn",
        grid, ratios, cfg.analysis["probing_adequacy"],
    )
    sweep.to_csv(OUTPUTS_DIR / "dark_ratio_calibration.csv", index=False)
    candidate_ratio = largest_ratio_under(sweep)
    n_controls_total = sum(len(v) for v in controls["asns"].values())
    log.info("dark-ratio false-positive sweep (full study period, %d controls, %d bins):\n%s",
              n_controls_total, len(grid), sweep.to_string(index=False))
    log.info("largest ratio with false-dark rate < 1%%: %s", candidate_ratio)

    print("\n=== D-013 step 4/5 candidates (PROPOSAL, not yet decided) ===")
    print(f"visibility_announced_min candidate: {valley['candidate_threshold']:.4f} "
          f"(valley [{valley['valley_lo']:.4f}, {valley['valley_hi']:.4f}], "
          f"empty_run={valley['empty_run']})")
    print(f"probing_dark_ratio candidate: {candidate_ratio} "
          f"(largest tested ratio with false-dark rate < 1%)")
    print("Full data: outputs/p0_visibility_histogram.csv, outputs/dark_ratio_calibration.csv")


if __name__ == "__main__":
    main()
