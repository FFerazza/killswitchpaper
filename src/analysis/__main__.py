"""Stage 5 CLI: build the joined, figure-ready tables under outputs/.

Usage:
    python -m src.analysis [--only visibility_by_type|bgp_vs_ioda|upstream_transitions|event_speed]

Each table is built from whatever stage outputs exist; missing inputs fail
with a message saying which stage to run.
"""

import argparse
from pathlib import Path

import pandas as pd

from src.common.config import CONFIG_DIR, DATA_DIR, OUTPUTS_DIR, Config
from src.common.log import get_logger
from src.analysis import joins, phase_breakdown, results_tex, series_comparison

log = get_logger("analysis")

TABLES = ["visibility_by_type", "bgp_vs_ioda", "upstream_transitions", "event_speed",
          "restoration_events", "restoration_by_type",
          "fine_restoration_order", "restoration_order_by_type",
          "visibility_bimodality", "phase_breakdown", "results_tex"]


def _load_visibility(min_fullfeed_peers: int, cc: str = "IR") -> pd.DataFrame:
    """Load the visibility series for one population (D-016 cc tag).

    The current tables are IR analyses; control-population BGP series (D-014
    artifact checks) select their cc explicitly. Series consolidated before
    D-016 carry no cc column and are IR-only by construction.

    D-020: (snapshot, family) cells with fewer than min_fullfeed_peers
    full-feed peers are DEGRADED and dropped; peers_total is the row's
    own-family full-feed count.
    """
    path = DATA_DIR / "bgp" / "visibility_timeseries.parquet"
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make bgp-ribs` (or test-week) first")
    df = pd.read_parquet(path)
    if "cc" not in df.columns:
        df["cc"] = "IR"
    df = joins.drop_degraded(df, min_fullfeed_peers)
    return df[df["cc"] == cc].reset_index(drop=True)


def _load_classification() -> pd.DataFrame:
    path = DATA_DIR / "population" / "ir_asn_classification.csv"
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make population` first")
    return pd.read_csv(path, dtype={"asn": int, "org_name": str, "type": str, "notes": str})


def _load_delegated_prefixes() -> pd.DataFrame:
    path = DATA_DIR / "population" / "ir_prefixes.csv"
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make population` first")
    return pd.read_csv(path, dtype={"prefix": str, "family": int})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    parser.add_argument("--only", choices=TABLES, help="build a single table")
    args = parser.parse_args()

    cfg = Config.load(args.config_dir)
    tables = [args.only] if args.only else TABLES
    min_ff = int(cfg.analysis["min_fullfeed_peers"])

    if "visibility_by_type" in tables:
        joins.visibility_by_type(
            _load_visibility(min_ff), _load_classification(),
            OUTPUTS_DIR / "visibility_by_type.parquet",
        )
    if "bgp_vs_ioda" in tables:
        # D-013: baselines from the fixed P0 reference window (data/ioda/baseline/),
        # thresholds provisional until the D-013 procedure finalizes them.
        joins.bgp_vs_ioda(
            _load_visibility(min_ff),
            DATA_DIR / "ioda" / "asn",
            DATA_DIR / "ioda" / "baseline" / "asn",
            visibility_announced_min=cfg.analysis["visibility_announced_min"],
            probing_dark_ratio=cfg.analysis["probing_dark_ratio"],
            probing_adequacy=cfg.analysis["probing_adequacy"],
            out_path=OUTPUTS_DIR / "bgp_vs_ioda.parquet",
            excluded_out_path=OUTPUTS_DIR / "probing_excluded_asns.csv",
        )
    if "upstream_transitions" in tables:
        joins.upstream_transitions(
            _load_visibility(min_ff), OUTPUTS_DIR / "upstream_transitions.parquet"
        )
    if "event_speed" in tables:
        # D-009: withdrawals reannounced within flap_threshold_s (same peer
        # session) are excluded from onset timing - a flap, not a real event.
        joins.event_speed(
            DATA_DIR / "bgp" / "events", OUTPUTS_DIR / "event_speed.parquet",
            flap_threshold_s=int(cfg.analysis["flap_threshold_s"]),
        )
    if "restoration_events" in tables:
        # D-023 (H3 centerpiece): needs the raw per-observed-prefix series
        # (not the per-AS collapse _load_visibility -> _per_as_visibility
        # produces for the other tables), so it loads visibility directly.
        p0 = cfg.phase_window("P0")
        p4 = cfg.phase_window("P4")
        study_end = cfg.study_period.end
        steady_state_start = study_end - int(cfg.analysis["steady_state_days"]) * 86400
        joins.restoration_events(
            _load_visibility(min_ff), _load_delegated_prefixes(),
            p0_start=p0.start, p0_end=p0.end, p4_start=p4.start,
            steady_state_start=steady_state_start,
            thresholds=list(cfg.analysis["restoration_thresholds"]),
            primary_threshold=float(cfg.analysis["restoration_primary_threshold"]),
            out_path=OUTPUTS_DIR / "restoration_events.parquet",
        )
    if "restoration_by_type" in tables:
        path = OUTPUTS_DIR / "restoration_events.parquet"
        if not path.exists():
            raise SystemExit(f"{path} not found - run `--only restoration_events` first")
        joins.restoration_by_type(
            pd.read_parquet(path), _load_classification(),
            p4_start=cfg.phase_window("P4").start,
            out_path=OUTPUTS_DIR / "restoration_by_type.parquet",
        )
    if "fine_restoration_order" in tables:
        # H3 companion (D-023): the may2026_restoration event window gives
        # real BGP-update timestamps, unlike the 8h primary-series grid.
        events_path = DATA_DIR / "bgp" / "events" / "may2026_restoration.parquet"
        if not events_path.exists():
            raise SystemExit(f"{events_path} not found - pull the may2026_restoration event window first")
        joins.fine_restoration_order(
            pd.read_parquet(events_path), _load_delegated_prefixes(),
            since_ts=cfg.phase_window("P4").start,
            out_path=OUTPUTS_DIR / "fine_restoration_order.parquet",
        )
    if "restoration_order_by_type" in tables:
        fine_path = OUTPUTS_DIR / "fine_restoration_order.parquet"
        restoration_path = OUTPUTS_DIR / "restoration_events.parquet"
        if not fine_path.exists():
            raise SystemExit(f"{fine_path} not found - run `--only fine_restoration_order` first")
        if not restoration_path.exists():
            raise SystemExit(f"{restoration_path} not found - run `--only restoration_events` first")
        joins.restoration_order_by_type(
            pd.read_parquet(fine_path), pd.read_parquet(restoration_path), _load_classification(),
            window_start=cfg.phase_window("P4").start,
            out_path=OUTPUTS_DIR / "restoration_order_by_type.parquet",
        )
    if "phase_breakdown" in tables:
        # Headline P0-P4 H1/H2/H3 numbers (previously only ever computed
        # ad hoc and reported in prose/memory, never saved as a committed,
        # reproducible artifact) + D-025's transition-window robustness
        # exhibits. All read from the just-built Stage 5 tables on disk.
        phases = {p: cfg.phase_window(p) for p in ["P0", "P1", "P2", "P3", "P4"]}
        bvi_path = OUTPUTS_DIR / "bgp_vs_ioda.parquet"
        ut_path = OUTPUTS_DIR / "upstream_transitions.parquet"
        vbt_path = OUTPUTS_DIR / "visibility_by_type.parquet"
        for p in (bvi_path, ut_path, vbt_path):
            if not p.exists():
                raise SystemExit(f"{p} not found - run the full pipeline first")
        bvi = pd.read_parquet(bvi_path)
        ut = pd.read_parquet(ut_path)
        vbt = pd.read_parquet(vbt_path)

        joins.write_parquet(
            phase_breakdown.dark_and_withdrawn_share(bvi, phases).reset_index(),
            OUTPUTS_DIR / "phase_breakdown_h1.parquet",
        )
        joins.write_parquet(
            phase_breakdown.transition_rate_by_phase(ut, phases).reset_index(),
            OUTPUTS_DIR / "phase_breakdown_h2.parquet",
        )
        joins.write_parquet(
            phase_breakdown.visibility_by_type_by_phase(vbt, phases).reset_index(),
            OUTPUTS_DIR / "phase_breakdown_h3_visibility.parquet",
        )

        # D-025 robustness: the raw snapshot trajectory across the measured
        # Feb 28 P1/P2 transition (the four 8h-grid snapshots straddling it).
        p2_start = cfg.phase_window("P2").start
        grid_step = cfg.rib_interval_hours * 3600
        grid_midnight = p2_start - (p2_start % grid_step)
        trajectory_ts = [grid_midnight + k * grid_step for k in range(4)]
        traj = phase_breakdown.snapshot_trajectory(bvi, trajectory_ts)
        traj.to_csv(OUTPUTS_DIR / "p1_p2_transition_snapshot_trajectory.csv", index=False)
        log.info("%d rows -> %s", len(traj),
                  OUTPUTS_DIR / "p1_p2_transition_snapshot_trajectory.csv")

        # D-025's own pre-committed +/-24h P1/P2 boundary sweep, plus a finer
        # intermediate grid showing where the metric mechanically breaks.
        shifts = [-86400, -43200, -14400, -7200, -3600, -1800, 0,
                  1800, 3600, 7200, 14400, 43200, 86400]
        sweep = phase_breakdown.boundary_sensitivity_sweep(bvi, ut, phases, "P1", shifts)
        sweep.to_csv(OUTPUTS_DIR / "p1_p2_boundary_sensitivity.csv", index=False)
        log.info("%d rows -> %s", len(sweep), OUTPUTS_DIR / "p1_p2_boundary_sensitivity.csv")

        # H1: does the probing collapse (P2 boundary, timed above) precede
        # the bulk BGP withdrawal wave? Percentiles restricted to ts >= P2
        # start avoid the pull window's pre-boundary buffer-day noise.
        feb_events_path = DATA_DIR / "bgp" / "events" / "feb2026_onset.parquet"
        if feb_events_path.exists():
            feb_events = pd.read_parquet(feb_events_path)
            wave = phase_breakdown.withdrawal_wave_timing(
                feb_events, phases["P2"].start, int(cfg.analysis["flap_threshold_s"]),
            )
            pd.DataFrame([wave]).to_csv(
                OUTPUTS_DIR / "feb2026_withdrawal_wave.csv", index=False
            )
            log.info("withdrawal wave timing -> %s",
                      OUTPUTS_DIR / "feb2026_withdrawal_wave.csv")

    if "visibility_bimodality" in tables:
        # D-012 two-series robustness exhibit (paper-two-series-justification
        # argument 3): demonstrates bimodality/threshold-insensitivity on the
        # actual overlapping data, primary vs RIS-secondary, never merged.
        ris_path = DATA_DIR / "bgp" / "visibility_timeseries_ris.parquet"
        if not ris_path.exists():
            raise SystemExit(f"{ris_path} not found - run `ribs-ris` backfill first")
        primary_raw = pd.read_parquet(DATA_DIR / "bgp" / "visibility_timeseries.parquet")
        ris_raw = pd.read_parquet(ris_path)
        comparison = series_comparison.visibility_distribution_comparison(
            primary_raw, ris_raw, min_ff,
        )
        joins.write_parquet(comparison, OUTPUTS_DIR / "visibility_bimodality_comparison.parquet")
        summary = series_comparison.bimodality_summary(comparison)
        joins.write_parquet(summary, OUTPUTS_DIR / "visibility_bimodality_summary.parquet")

    if "results_tex" in tables:
        results_tex.write_results_tex(cfg, results_tex.PAPER_DIR / "results.tex")


if __name__ == "__main__":
    main()
