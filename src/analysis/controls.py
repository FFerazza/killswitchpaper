"""D-014 artifact check: does an Iranian anomaly also appear in the controls?

For every test-week snapshot bin, computes the share of frozen control ASNs
whose probing signal is "dark" under the same D-013 rule applied to Iran
(probing < probing_dark_ratio x own Sept-2025 baseline). A bin where the
control dark-share >= artifact_bin_share (frozen in config/controls.yaml)
means the Iranian pattern in that bin is a measurement artifact.

This is the IODA-side check only (no BGP visibility needed for controls);
BGP-side control tracking enters Stage 2 with the full-period run.

Usage:
    python -m src.analysis.controls [--window NAME]   # default: test_week
Output:
    outputs/control_artifact_check[_NAME].csv + verdict logged per bin
    (test_week keeps the original bare filename for backward compatibility).
"""

import argparse
from pathlib import Path

import pandas as pd
import yaml

from src.common.config import CONFIG_DIR, DATA_DIR, OUTPUTS_DIR, Config
from src.common.log import get_logger
from src.common.timeutil import snapshot_times, to_iso
from src.analysis.joins import _PROBING_SIGNAL, _probing_baseline

log = get_logger("analysis.controls")


def control_dark_shares(
    control_asns: dict[str, list[int]],
    ioda_asn_dir: Path,
    baseline_dir: Path,
    grid: list[int],
    probing_dark_ratio: float,
    probing_adequacy: dict,
) -> pd.DataFrame:
    """Per grid bin: share of (adequate) control ASNs whose probing is dark."""
    rows = []
    for cc, asns in control_asns.items():
        for asn in asns:
            baseline, adequate, _ = _probing_baseline(
                baseline_dir, asn,
                probing_adequacy["min_nonzero_share"], probing_adequacy["min_median"],
            )
            path = ioda_asn_dir / f"{asn}.parquet"
            if not adequate or not path.exists():
                continue
            sig = pd.read_parquet(path)
            sig = sig[sig["datasource"] == _PROBING_SIGNAL].dropna(subset=["value"])
            if sig.empty:
                continue
            sig = sig.sort_values("ts")
            grid_df = pd.DataFrame({"ts": grid})
            merged = pd.merge_asof(
                grid_df, sig[["ts", "value"]], on="ts", direction="backward"
            )
            for r in merged.itertuples():
                if pd.isna(r.value):
                    continue
                rows.append({
                    "ts": int(r.ts), "country": cc, "asn": asn,
                    "dark": bool(r.value < probing_dark_ratio * baseline),
                })
    per_asn = pd.DataFrame(rows)
    if per_asn.empty:
        raise SystemExit("no control observations - pull control IODA data first")
    shares = (
        per_asn.groupby("ts")
        .agg(n_controls=("asn", "nunique"), dark_share=("dark", "mean"))
        .reset_index()
    )
    return shares


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", default="test_week",
                    help="named window from phases.yaml to check (default: test_week)")
    args = ap.parse_args()

    cfg = Config.load()
    controls_path = CONFIG_DIR / "controls.yaml"
    if not controls_path.exists():
        raise SystemExit("config/controls.yaml missing - run python -m src.population.controls")
    with open(controls_path) as f:
        controls = yaml.safe_load(f)

    w = cfg.window_by_name(args.window)
    grid = list(snapshot_times(w.start, w.end, cfg.rib_interval_hours))
    shares = control_dark_shares(
        controls["asns"],
        DATA_DIR / "ioda" / "asn",
        DATA_DIR / "ioda" / "baseline" / "asn",
        grid,
        cfg.analysis["probing_dark_ratio"],
        cfg.analysis["probing_adequacy"],
    )
    threshold = float(controls["artifact_bin_share"])
    shares["artifact"] = shares["dark_share"] >= threshold

    suffix = "" if args.window == "test_week" else f"_{args.window}"
    out = OUTPUTS_DIR / f"control_artifact_check{suffix}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    shares.to_csv(out, index=False)
    for r in shares.itertuples():
        log.info("%s: %d controls, dark_share=%.3f%s",
                 to_iso(r.ts), r.n_controls, r.dark_share,
                 "  ** ARTIFACT BIN **" if r.artifact else "")
    n_bad = int(shares["artifact"].sum())
    log.info("verdict: %d/%d bins artifact-flagged (threshold %.2f) -> %s",
             n_bad, len(shares), threshold, out)


if __name__ == "__main__":
    main()
