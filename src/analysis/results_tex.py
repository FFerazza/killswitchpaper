"""Emits paper/results.tex: every empirical number the paper's prose cites,
as \\newcommand macros, read from committed outputs/*.parquet|csv (never
computed here, only formatted). CLAUDE.md: "No empirical number is ever
typed into .tex by hand." If a draft sentence needs a number with no macro
yet, add it here - never hand-type it into the .tex source.

Also emits paper/tables/*.tex: generated LaTeX table fragments for the
per-type / per-window comparisons that are naturally tabular rather than
single inline numbers (H3 restoration-by-type, H4 cross-window, etc).

Usage:
    python -m src.analysis --only results_tex
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from src.common.config import CONFIG_DIR, DATA_DIR, OUTPUTS_DIR, PHASE_NAMES, Config
from src.common.log import get_logger

log = get_logger("analysis.results_tex")

PAPER_DIR = Path(__file__).resolve().parents[2] / "paper"


def _fmt_human_dt(ts: int, always_time: bool = False) -> str:
    """Reader-facing date, per CLAUDE.md numbers-via-macro rule but never a
    raw ISO 8601 string in prose - full ISO timestamps are for logs/storage,
    not for people. Drops the time-of-day when it's exactly midnight (a
    day-granularity boundary) UNLESS always_time is set - use that for any
    set of timestamps being compared to each other within the same day,
    where dropping the time would make two different instants print
    identically (e.g. a same-day trajectory of snapshots)."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if dt.hour == 0 and dt.minute == 0 and not always_time:
        return dt.strftime("%-d %B %Y")
    return dt.strftime("%-d %B %Y, %H:%M UTC")


def _fmt_pct(x: float, decimals: int = 2) -> str:
    return f"{x * 100:.{decimals}f}\\%"


def _fmt_num(x, decimals: int = 0) -> str:
    if decimals == 0:
        return f"{int(round(x)):,}"
    return f"{x:.{decimals}f}"


def _fmt_hours(seconds: float) -> str:
    return f"{seconds / 3600:.1f}"


def _fmt_min(seconds: float) -> str:
    return f"{seconds / 60:.1f}"


def _macro(name: str, value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z]+", name):
        raise ValueError(
            f"macro name {name!r} is not letters-only - LaTeX \\newcommand "
            "names allow no digits/underscores"
        )
    if name.lower().startswith("end"):
        raise ValueError(
            f"macro name {name!r} starts with 'end' - LaTeX \\newcommand "
            "reserves that whole namespace for \\end{environment}"
        )
    return f"\\newcommand{{\\{name}}}{{{value}}}"


def _camel(*parts: str) -> str:
    """LaTeX \\newcommand names allow only letters - strip digits/underscores,
    then CamelCase each underscore/digit-delimited word."""
    words = re.split(r"[_\d]+", "_".join(parts))
    return "".join(w.title() for w in words if w)


_PHASE_WORD = {"P0": "PZero", "P1": "POne", "P2": "PTwo", "P3": "PThree", "P4": "PFour"}


def build_macros(cfg: Config) -> list[str]:
    lines: list[str] = []

    def add(name, value):
        lines.append(_macro(name, value))

    # --- Population / classification scale (Stage 1, D-018/D-019) ---
    asns = pd.read_csv(DATA_DIR / "population" / "ir_asns.csv")
    prefixes = pd.read_csv(DATA_DIR / "population" / "ir_prefixes.csv")
    cls = pd.read_csv(
        DATA_DIR / "population" / "ir_asn_classification.csv",
        dtype={"asn": int, "org_name": str, "type": str, "notes": str},
    )
    add("nIrAsns", _fmt_num(len(asns)))
    add("nIrPrefixes", _fmt_num(len(prefixes)))
    add("nClassified", _fmt_num(cls["type"].notna().sum()))
    for t, n in cls["type"].value_counts().items():
        add(f"nType{_camel(t)}", _fmt_num(n))

    # --- D-014/D-016: control population ---
    controls_path = CONFIG_DIR / "controls.yaml"
    if controls_path.exists():
        with open(controls_path) as f:
            controls = yaml.safe_load(f)
        add("nControlCountries", _fmt_num(len(controls["countries"])))
        add("nControlAsnsPerCountry", _fmt_num(len(next(iter(controls["asns"].values())))))
        add("nControlAsnsTotal", _fmt_num(sum(len(v) for v in controls["asns"].values())))
        add("controlArtifactBinShare", _fmt_pct(controls["artifact_bin_share"]))
    control_prefixes_path = DATA_DIR / "population" / "control_prefixes.csv"
    if control_prefixes_path.exists():
        add("nControlPrefixes", _fmt_num(len(pd.read_csv(control_prefixes_path))))

    # --- D-002: full-feed peer qualification ---
    add("fullFeedMinIpvFour", _fmt_num(cfg.full_feed_min_prefixes["ipv4"]))
    add("fullFeedMinIpvSix", _fmt_num(cfg.full_feed_min_prefixes["ipv6"]))
    add("ribIntervalHours", _fmt_num(cfg.rib_interval_hours))

    # --- D-020: degraded-snapshot floor ---
    add("minFullfeedPeers", _fmt_num(cfg.analysis["min_fullfeed_peers"]))

    # --- D-009: flap-filter threshold ---
    add("flapThresholdSeconds", _fmt_num(cfg.analysis["flap_threshold_s"]))

    # --- D-023: restoration thresholds ---
    add("restorationPrimaryThresholdPct", _fmt_pct(cfg.analysis["restoration_primary_threshold"], 0))
    add("steadyStateDays", _fmt_num(cfg.analysis["steady_state_days"]))

    # --- Reference dates mentioned in prose (human-readable, never raw ISO) ---
    baseline_w = cfg.probing_baseline_window
    add("probingBaselineStart", _fmt_human_dt(baseline_w.start))
    add("probingBaselineEnd", _fmt_human_dt(baseline_w.end))
    jan_w = cfg.window_by_name("jan2026_event")
    add("janEventPullStart", _fmt_human_dt(jan_w.start))
    add("janEventPullEnd", _fmt_human_dt(jan_w.end))

    # --- D-013 (D-005): probing adequacy rule ---
    add("probingAdequacyMinNonzeroShare", _fmt_pct(cfg.analysis["probing_adequacy"]["min_nonzero_share"], 0))
    add("probingAdequacyMinMedian", _fmt_num(cfg.analysis["probing_adequacy"]["min_median"]))
    add("nProbingExcluded", _fmt_num(len(pd.read_csv(OUTPUTS_DIR / "probing_excluded_asns.csv"))))

    # --- D-026 (resolves D-013 steps 4/5): final thresholds ---
    add("visibilityAnnouncedMin", f"{cfg.analysis['visibility_announced_min']:.2f}")
    add("probingDarkRatio", f"{cfg.analysis['probing_dark_ratio']:.2f}")
    valley_path = OUTPUTS_DIR / "p0_visibility_valley_summary.csv"
    if valley_path.exists():
        valley = pd.read_csv(valley_path).iloc[0]
        add("visibilityValleyLo", f"{valley['valley_lo']:.3f}")
        add("visibilityValleyHi", f"{valley['valley_hi']:.3f}")
    sweep_path = OUTPUTS_DIR / "dark_ratio_calibration.csv"
    if sweep_path.exists():
        sweep = pd.read_csv(sweep_path)
        crossing = sweep[sweep["false_dark_rate"] >= 0.01].sort_values("ratio").head(1)
        if not crossing.empty:
            add("darkRatioCrossoverRatio", f"{crossing.iloc[0]['ratio']:.2f}")
            add("darkRatioCrossoverRate", _fmt_pct(crossing.iloc[0]["false_dark_rate"]))

    # --- H1: per-phase dark/withdrawn share (phase_breakdown_h1.parquet) ---
    h1 = pd.read_parquet(OUTPUTS_DIR / "phase_breakdown_h1.parquet").set_index("phase")
    for p in ["P0", "P1", "P2", "P3", "P4"]:
        pw = _PHASE_WORD[p]
        add(f"darkShare{pw}", _fmt_pct(h1.loc[p, "dark_share"]))
        add(f"withdrawnShare{pw}", _fmt_pct(h1.loc[p, "withdrawn_share"]))
        add(f"nObs{pw}", _fmt_num(h1.loc[p, "n"]))

    # --- H2: per-phase upstream-transition rate ---
    h2 = pd.read_parquet(OUTPUTS_DIR / "phase_breakdown_h2.parquet").set_index("phase")
    for p in ["P0", "P1", "P2", "P3", "P4"]:
        add(f"transitionRate{_PHASE_WORD[p]}", _fmt_pct(h2.loc[p, "transition_rate"]))

    # --- H3: classification agreement (D-018 blind validation) ---
    kappa = pd.read_csv(OUTPUTS_DIR / "classification_agreement_summary.csv").iloc[0]
    add("kappaN", _fmt_num(kappa["n"]))
    add("kappaAgreePct", _fmt_pct(kappa["percent_agreement"]))
    add("kappaValue", f"{kappa['cohen_kappa']:.3f}")

    # --- H3: restoration-by-type (D-023 fine-grained companion, event-stream res.) ---
    order = pd.read_parquet(OUTPUTS_DIR / "restoration_order_by_type.parquet").set_index("type")
    for t in order.index:
        add(f"restoreDelayMin{_camel(t)}", _fmt_min(order.loc[t, "median_delay_s"]))
    fastest = order["median_delay_s"].idxmin()
    slowest = order["median_delay_s"].idxmax()
    add("restoreFastestType", fastest.replace("_", " "))
    add("restoreSlowestType", slowest.replace("_", " "))
    add("restoreFastestMin", _fmt_min(order.loc[fastest, "median_delay_s"]))
    add("restoreSlowestMin", _fmt_min(order.loc[slowest, "median_delay_s"]))

    # --- H3: never-restored share (primary-series, coarse) ---
    by_type = pd.read_parquet(OUTPUTS_DIR / "restoration_by_type.parquet").set_index("type")
    for t in by_type.index:
        never_pct = by_type.loc[t, "n_never_restored"] / by_type.loc[t, "n_blocks"]
        add(f"neverRestored{_camel(t)}", _fmt_pct(never_pct))

    # --- H4: event_speed cross-window comparison ---
    ev = pd.read_parquet(OUTPUTS_DIR / "event_speed.parquet").set_index("window")
    for w in ev.index:
        key = _camel(w)
        add(f"duration{key}RangeHours", _fmt_hours(ev.loc[w, "duration_p5_p95_s"]))
        add(f"duration{key}FullRangeHours", _fmt_hours(ev.loc[w, "duration_s"]))
        add(f"duration{key}MedianHours", _fmt_hours(ev.loc[w, "duration_p50_s"]))
        add(f"nWithdrawn{key}", _fmt_num(ev.loc[w, "n_prefixes_withdrawn"]))

    # --- D-008 control-population artifact check (full study period) ---
    ctrl = pd.read_csv(OUTPUTS_DIR / "control_artifact_check_study_period.csv")
    add("nControlBins", _fmt_num(len(ctrl)))
    add("nControlArtifactBins", _fmt_num(ctrl["artifact"].sum()))
    add("controlMeanDarkShare", _fmt_pct(ctrl["dark_share"].mean()))
    add("controlMaxDarkShare", _fmt_pct(ctrl["dark_share"].max()))
    for p in ["P0", "P1", "P2", "P3", "P4"]:
        w = cfg.phase_window(p)
        seg = ctrl[(ctrl["ts"] >= w.start) & (ctrl["ts"] < w.end)]
        add(f"controlDarkShare{_PHASE_WORD[p]}", _fmt_pct(seg["dark_share"].mean()))

    # --- Two-series bimodality exhibit (D-012 argument 3) ---
    bim = pd.read_parquet(OUTPUTS_DIR / "visibility_bimodality_summary.parquet").set_index("series")
    for s in ["primary", "ris"]:
        key = s.title()
        add(f"bimodalAmbiguous{key}", _fmt_pct(bim.loc[s, "ambiguous_share"]))
        add(f"bimodalNearOne{key}", _fmt_pct(bim.loc[s, "near_one_share"]))
        add(f"bimodalNearZero{key}", _fmt_pct(bim.loc[s, "near_zero_share"]))

    # --- RIPEstat validation (Stage 4) ---
    ripestat = pd.read_csv(OUTPUTS_DIR / "ripestat_comparison.csv")
    add("ripestatN", _fmt_num(len(ripestat)))
    add("ripestatAgreeN", _fmt_num(ripestat["agree"].sum()))

    # --- Phase boundary dates (D-025), human-readable (never raw ISO 8601
    # in prose - that's a storage/log format, not something a reader should
    # have to parse) + reader-facing phase names, for figure captions,
    # prose, and the generated phase table. ---
    for p in ["P0", "P1", "P2", "P3", "P4"]:
        w = cfg.phase_window(p)
        pw = _PHASE_WORD[p]
        # NB: LaTeX \newcommand forbids any name starting with "end" (that
        # whole namespace is reserved for \end{environment}) - "boundary"
        # suffix avoids it rather than a bare "end" prefix/suffix.
        add(f"{pw}Start", _fmt_human_dt(w.start))
        add(f"{pw}Boundary", _fmt_human_dt(w.end))
        add(f"{pw}Name", PHASE_NAMES[p])

    # --- D-025 robustness: raw Feb 28 P1/P2 transition trajectory ---
    traj_path = OUTPUTS_DIR / "p1_p2_transition_snapshot_trajectory.csv"
    if traj_path.exists():
        traj = pd.read_csv(traj_path).reset_index(drop=True)
        traj_labels = ["PrevMidnight", "TransitionMorning", "TransitionAfternoon", "NextMidnight"]
        for label, row in zip(traj_labels, traj.itertuples()):
            add(f"trajDarkShare{label}", _fmt_pct(row.dark_share))
            add(f"trajTime{label}", _fmt_human_dt(int(row.ts), always_time=True))

    # --- H1: BGP withdrawal-wave timing vs. the probing-based P2 boundary ---
    wave_path = OUTPUTS_DIR / "feb2026_withdrawal_wave.csv"
    if wave_path.exists():
        wave = pd.read_csv(wave_path).iloc[0]
        add("withdrawalWaveTMin", _fmt_human_dt(int(wave["t_min"])))
        add("withdrawalWaveTPFive", _fmt_human_dt(int(wave["t_p5"])))
        add("withdrawalWaveTPFifty", _fmt_human_dt(int(wave["t_p50"])))
        add("withdrawalWaveNPrefixes", _fmt_num(wave["n_prefixes"]))
        gap_s = int(wave["t_p5"]) - cfg.phase_window("P2").start
        add("withdrawalWaveGapMinutes", _fmt_num(gap_s / 60))

    # --- D-025 robustness: +/-24h P1/P2 boundary sensitivity sweep ---
    sweep_path = OUTPUTS_DIR / "p1_p2_boundary_sensitivity.csv"
    if sweep_path.exists():
        bsweep = pd.read_csv(sweep_path).set_index("shift_s")
        add("pTwoDarkShareShiftMinusOneDay", _fmt_pct(bsweep.loc[-86400, "P2_dark_share"]))
        add("pTwoDarkShareShiftZero", _fmt_pct(bsweep.loc[0, "P2_dark_share"]))

    return lines


def write_results_tex(cfg: Config, out_path: Path) -> None:
    lines = build_macros(cfg)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "% GENERATED FILE - never hand-edit.\n"
        "% Written by src/analysis/results_tex.py "
        "(python -m src.analysis --only results_tex).\n"
    )
    out_path.write_text(header + "\n".join(lines) + "\n")
    log.info("%d macros -> %s", len(lines), out_path)


def main() -> None:
    cfg = Config.load(CONFIG_DIR)
    write_results_tex(cfg, PAPER_DIR / "results.tex")


if __name__ == "__main__":
    main()
