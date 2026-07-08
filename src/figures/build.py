"""Generates every figure in the paper from committed outputs/*.parquet|csv
and data/*.parquet (never re-derives numbers - if a figure needs a number
not already computed by src/analysis/, add it there first).

Usage:
    python -m src.figures [--only NAME]
Output:
    paper/figures/*.pdf
"""

import argparse

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from src.common.config import CONFIG_DIR, DATA_DIR, OUTPUTS_DIR, PHASE_NAMES, Config
from src.common.log import get_logger
from src.figures.style import (
    CATEGORICAL,
    INK_MUTED,
    INK_SECONDARY,
    STATUS,
    apply_style,
    clean_axes,
    savefig,
)

log = get_logger("figures")

FIGURES = [
    "timeline", "state_share", "control_falsification", "h2_churn",
    "h3_visibility_by_type", "h3_restoration_speed", "h4_comparison",
    "bimodality", "transition_zoom",
]

_PHASE_LABELS = ["P0", "P1", "P2", "P3", "P4"]
_PHASE_DISPLAY = [PHASE_NAMES[p] for p in _PHASE_LABELS]

_EVENT_DISPLAY = {
    "nov2019": "Nov 2019",
    "jun2025": "Jun 2025",
    "feb2026_onset": "Feb 2026\n(onset)",
    "may2026_restoration": "May 2026\n(recovery)",
    "jan2026_event": "Jan 2026",
}


def _ts_to_dt(ts):
    return pd.to_datetime(ts, unit="s", utc=True)


def _annotate_phases(ax, cfg: Config, y_top: float) -> None:
    for i, p in enumerate(_PHASE_LABELS):
        w = cfg.phase_window(p)
        ax.axvline(_ts_to_dt(w.start), color=INK_MUTED, linewidth=0.6, linestyle=":")
        mid = _ts_to_dt((w.start + w.end) // 2)
        ax.text(mid, y_top, PHASE_NAMES[p], ha="center", va="bottom", fontsize=6.5,
                 color=INK_SECONDARY, rotation=0)


def _annotate_phases_zoom(ax, cfg: Config, y_top: float) -> None:
    """Post-baseline phase annotation (P1-P4) for the zoomed timeline panel.

    Onset (P2) is a matter of hours next to Prelude's ~7 weeks and
    Plateau's ~3 months, so even zoomed to just the post-baseline window it
    is too narrow for a centered label to sit over without colliding with
    its neighbors. Two things fix that: staggering label height so
    adjacent labels don't occupy the same row, and drawing Onset as a
    filled band (not just a boundary line) with a leader line to its label,
    so the phase is visible even at sub-pixel width.
    """
    labels = ["P1", "P2", "P3", "P4"]
    stagger = [y_top, y_top + 0.16, y_top, y_top + 0.16]
    for i, p in enumerate(labels):
        w = cfg.phase_window(p)
        start_dt = _ts_to_dt(w.start)
        ax.axvline(start_dt, color=INK_MUTED, linewidth=0.6, linestyle=":")
        mid = _ts_to_dt((w.start + w.end) // 2)
        if p == "P2":
            ax.axvspan(start_dt, _ts_to_dt(w.end), color=CATEGORICAL[2], alpha=0.35, zorder=0)
        ax.annotate(
            PHASE_NAMES[p], xy=(mid, 1.0), xytext=(mid, stagger[i]),
            ha="center", va="bottom", fontsize=6.5, color=INK_SECONDARY,
            arrowprops=dict(arrowstyle="-", color=INK_MUTED, linewidth=0.5,
                             shrinkA=0, shrinkB=2),
        )


def fig_timeline(cfg: Config) -> None:
    """Headline figure: country-level active-probing signal, full study
    period, native resolution, phases + named events annotated.

    Two panels rather than one: Baseline alone (P0) spans about 8 months,
    versus about 6 months for the other four phases combined, and within
    those six months Onset (P2) is a matter of hours. A single linear axis
    across the full period cannot give Prelude and Onset distinguishable
    space next to a Baseline that long, so the top panel shows the full
    period for context (with the post-baseline window it zooms into marked)
    and the bottom panel re-plots just that post-baseline window at its own
    scale, where Prelude, Onset, Plateau, and Restoration each get legible
    room.
    """
    df = pd.read_parquet(DATA_DIR / "ioda" / "country_IR.parquet")
    ping = df[df["datasource"] == "ping-slash24"].sort_values("ts")
    baseline = pd.read_parquet(DATA_DIR / "ioda" / "baseline" / "country_IR.parquet")
    baseline_median = baseline[baseline["datasource"] == "ping-slash24"]["value"].median()
    ratio = ping["value"] / baseline_median
    dt = _ts_to_dt(ping["ts"])

    p0 = cfg.phase_window("P0")
    zoom_start = cfg.phase_window("P1").start
    zoom_end = cfg.phase_window("P4").end
    zoom_mask = (ping["ts"] >= zoom_start) & (ping["ts"] < zoom_end)

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(7.0, 4.6), height_ratios=[1, 1.5])

    ax_top.plot(dt, ratio, color=CATEGORICAL[0], linewidth=0.6)
    ax_top.axhline(cfg.analysis["probing_dark_ratio"], color=STATUS["critical"],
                    linewidth=0.8, linestyle="--", label="shutdown threshold")
    ax_top.axvspan(_ts_to_dt(p0.start), _ts_to_dt(p0.end), color=INK_MUTED,
                    alpha=0.10, zorder=0)
    ax_top.text(_ts_to_dt((p0.start + p0.end) // 2), 1.08, "Baseline",
                ha="center", va="bottom", fontsize=6.5, color=INK_SECONDARY)
    ax_top.axvspan(_ts_to_dt(zoom_start), _ts_to_dt(zoom_end), color=CATEGORICAL[0],
                    alpha=0.10, zorder=0)
    ax_top.text(_ts_to_dt((zoom_start + zoom_end) // 2), 1.08, "zoomed below",
                ha="center", va="bottom", fontsize=6.5, color=INK_SECONDARY,
                style="italic")
    ax_top.set_title("Full study period", fontsize=8, loc="left", color=INK_SECONDARY)
    ax_top.set_ylabel("responsiveness\n(rel. to normal)")
    ax_top.set_ylim(0, 1.22)
    ax_top.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax_top.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax_top.legend(loc="lower left", fontsize=7)
    clean_axes(ax_top)

    ax_bot.plot(dt[zoom_mask], ratio[zoom_mask], color=CATEGORICAL[0], linewidth=0.8)
    ax_bot.axhline(cfg.analysis["probing_dark_ratio"], color=STATUS["critical"],
                    linewidth=0.8, linestyle="--")
    _annotate_phases_zoom(ax_bot, cfg, 1.08)
    ax_bot.set_title("Prelude through Restoration (zoomed)", fontsize=8, loc="left",
                      color=INK_SECONDARY)
    ax_bot.set_ylabel("responsiveness\n(rel. to normal)")
    ax_bot.set_ylim(0, 1.3)
    ax_bot.set_xlim(_ts_to_dt(zoom_start), _ts_to_dt(zoom_end))
    ax_bot.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax_bot.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    clean_axes(ax_bot)

    fig.tight_layout()
    savefig(fig, "timeline")
    plt.close(fig)


def fig_state_share(cfg: Config) -> None:
    """H1: announced_but_dark / withdrawn share by phase."""
    h1 = pd.read_parquet(OUTPUTS_DIR / "phase_breakdown_h1.parquet").set_index("phase")
    h1 = h1.reindex(_PHASE_LABELS)
    x = range(len(_PHASE_LABELS))
    fig, ax = plt.subplots(figsize=(4.4, 2.8))
    width = 0.35
    ax.bar([i - width / 2 for i in x], h1["dark_share"] * 100, width,
           label="announced but dark", color=CATEGORICAL[5])
    ax.bar([i + width / 2 for i in x], h1["withdrawn_share"] * 100, width,
           label="withdrawn from routing", color=CATEGORICAL[0])
    ax.set_xticks(list(x))
    ax.set_xticklabels(_PHASE_DISPLAY, fontsize=7.5)
    ax.set_ylabel("share of networks (%)")
    ax.legend(fontsize=7)
    clean_axes(ax)
    fig.tight_layout()
    savefig(fig, "state_share")
    plt.close(fig)


def fig_control_falsification(cfg: Config) -> None:
    """H1 robustness: IR dark share vs control-population dark share by phase."""
    h1 = pd.read_parquet(OUTPUTS_DIR / "phase_breakdown_h1.parquet").set_index("phase")
    h1 = h1.reindex(_PHASE_LABELS)
    ctrl = pd.read_csv(OUTPUTS_DIR / "control_artifact_check_study_period.csv")
    ctrl_by_phase = []
    for p in _PHASE_LABELS:
        w = cfg.phase_window(p)
        seg = ctrl[(ctrl["ts"] >= w.start) & (ctrl["ts"] < w.end)]
        ctrl_by_phase.append(seg["dark_share"].mean() * 100)

    x = range(len(_PHASE_LABELS))
    fig, ax = plt.subplots(figsize=(4.4, 2.8))
    ax.plot(x, h1["dark_share"] * 100, marker="o", color=CATEGORICAL[5], label="Iran")
    ax.plot(x, ctrl_by_phase, marker="o", color=CATEGORICAL[2],
             label="control countries")
    ax.set_xticks(list(x))
    ax.set_xticklabels(_PHASE_DISPLAY, fontsize=7.5)
    ax.set_ylabel("share of networks unreachable (%)")
    ax.legend(fontsize=7)
    clean_axes(ax)
    fig.tight_layout()
    savefig(fig, "control_falsification")
    plt.close(fig)


def fig_h2_churn(cfg: Config) -> None:
    """H2: upstream-set transition rate by phase."""
    h2 = pd.read_parquet(OUTPUTS_DIR / "phase_breakdown_h2.parquet").set_index("phase")
    h2 = h2.reindex(_PHASE_LABELS)
    fig, ax = plt.subplots(figsize=(4.4, 2.8))
    ax.bar(_PHASE_DISPLAY, h2["transition_rate"] * 100, color=CATEGORICAL[0])
    ax.tick_params(axis="x", labelsize=7.5)
    ax.set_ylabel("share of networks that changed\nupstream provider (%)")
    clean_axes(ax)
    fig.tight_layout()
    savefig(fig, "h2_churn")
    plt.close(fig)


def fig_h3_visibility_by_type(cfg: Config) -> None:
    """H3: BGP visibility_mean by classification type over time (monthly
    mean). 11 classification types exceed the 8-hue categorical palette, so
    rather than cycling colors (which would silently reuse a hue across two
    unrelated types), this shows the full population as a min-max band with
    only the two analytically distinguished types called out by name: mobile
    (the persistent lowest-mean type) and unclassified (the most volatile).
    """
    vbt = pd.read_parquet(OUTPUTS_DIR / "visibility_by_type.parquet")
    vbt["month"] = _ts_to_dt(vbt["ts"]).dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()
    monthly = vbt.groupby(["month", "type"])["visibility_mean"].mean().reset_index()
    monthly["visibility_pct"] = monthly["visibility_mean"] * 100
    band = monthly.groupby("month")["visibility_pct"].agg(["min", "max"]).reset_index()

    fig, ax = plt.subplots(figsize=(6.5, 2.9))
    ax.fill_between(band["month"], band["min"], band["max"],
                     color=CATEGORICAL[0], alpha=0.15, label="all other categories (range)")
    for t, label, color in [("mobile", "mobile", CATEGORICAL[5]),
                             ("unclassified", "unclassified", CATEGORICAL[2])]:
        sub = monthly[monthly["type"] == t].sort_values("month")
        ax.plot(sub["month"], sub["visibility_pct"], linewidth=1.3, color=color, label=label)
    ax.set_ylabel("routes visible (%)")
    ax.set_ylim(85, 102)
    _annotate_phases(ax, cfg, 100)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.legend(fontsize=7, loc="lower left")
    clean_axes(ax)
    fig.tight_layout()
    savefig(fig, "h3_visibility_by_type")
    plt.close(fig)


def fig_h3_restoration_speed(cfg: Config) -> None:
    """H3 centerpiece: median restoration delay from P4 boundary, by type
    (event-stream resolution, D-023 fine-grained companion). Each bar is
    already directly labeled on the y-axis, so color here would be purely
    decorative identity-duplication - a single flat hue is used instead of
    cycling the (8-hue) categorical palette across 11 bars, which would
    silently reuse colors across unrelated types."""
    order = pd.read_parquet(OUTPUTS_DIR / "restoration_order_by_type.parquet")
    order = order.sort_values("median_delay_s")
    minutes = order["median_delay_s"] / 60
    fig, ax = plt.subplots(figsize=(5.0, 3.2))
    ax.barh(order["type"].str.replace("_", " "), minutes, color=CATEGORICAL[0])
    ax.set_xlabel("typical time to reconnect after\nrecovery began (minutes)")
    clean_axes(ax)
    fig.tight_layout()
    savefig(fig, "h3_restoration_speed")
    plt.close(fig)


def fig_h4_comparison(cfg: Config) -> None:
    """H4: cross-window onset/restoration duration comparison."""
    ev = pd.read_parquet(OUTPUTS_DIR / "event_speed.parquet").set_index("window")
    order = [w for w in ["nov2019", "jun2025", "feb2026_onset", "may2026_restoration",
                          "jan2026_event"] if w in ev.index]
    ev = ev.loc[order]
    x = range(len(order))
    width = 0.35
    fig, ax = plt.subplots(figsize=(5.5, 2.9))
    ax.bar([i - width / 2 for i in x], ev["duration_p5_p95_s"] / 3600, width,
           label="typical range (5th-95th pct.)", color=CATEGORICAL[0])
    ax.bar([i + width / 2 for i in x], ev["duration_p50_s"] / 3600, width,
           label="typical delay (median)", color=CATEGORICAL[2])
    ax.set_xticks(list(x))
    ax.set_xticklabels([_EVENT_DISPLAY[w] for w in order], fontsize=7)
    ax.set_ylabel("hours")
    ax.legend(fontsize=7)
    clean_axes(ax)
    fig.tight_layout()
    savefig(fig, "h4_comparison")
    plt.close(fig)


def fig_bimodality(cfg: Config) -> None:
    """D-012 argument 3: visibility distribution, primary vs RIS-secondary,
    at their shared snapshots - the two-series threshold-insensitivity exhibit."""
    # Filled, semi-transparent overlapping histograms blend into an
    # unlabeled third color wherever both series have mass - which, for two
    # distributions this similar, is nearly everywhere. Outline-only
    # ("step") histograms avoid that: exactly two colors ever appear, both
    # in the legend, and the shapes are still directly comparable.
    comp = pd.read_parquet(OUTPUTS_DIR / "visibility_bimodality_comparison.parquet")
    n_bins = 40
    bin_width = 1 / n_bins
    bins = [i * bin_width for i in range(n_bins + 1)]
    # Must match series_comparison.py's ambiguous_band default (0.1, 0.9) -
    # the exact band the bimodalAmbiguous* macros (cited in the caption) are
    # computed over, marked here so the figure and the prose number tie
    # together visibly rather than by coincidence.
    ambiguous_lo, ambiguous_hi = 0.1, 0.9

    fig, ax = plt.subplots(figsize=(4.8, 3.0))
    ax.axvspan(ambiguous_lo, ambiguous_hi, color=INK_MUTED, alpha=0.08, zorder=0)
    ax.hist(comp[comp["series"] == "primary"]["visibility"], bins=bins,
            histtype="step", linewidth=1.6, color=CATEGORICAL[0],
            label="main measurement", density=True)
    ax.hist(comp[comp["series"] == "ris"]["visibility"], bins=bins,
            histtype="step", linewidth=1.6, color=CATEGORICAL[1],
            label="wider measurement", density=True)
    ax.axvline(ambiguous_lo, color=INK_MUTED, linewidth=0.6, linestyle=":")
    ax.axvline(ambiguous_hi, color=INK_MUTED, linewidth=0.6, linestyle=":")
    ax.text((ambiguous_lo + ambiguous_hi) / 2, 2, "ambiguous middle",
            ha="center", va="center", fontsize=6.5, color=INK_SECONDARY)
    ax.set_xlabel("visibility of an individual address block\n"
                   "(fraction of monitoring collectors reporting it, 0-1)")
    ax.set_ylabel("probability density (log scale)")
    ax.set_yscale("log")
    ax.set_xlim(0, 1)
    ax.legend(fontsize=7, loc="upper left")
    clean_axes(ax)
    fig.tight_layout()
    savefig(fig, "bimodality")
    plt.close(fig)


def fig_transition_zoom(cfg: Config) -> None:
    """D-025 robustness: raw snapshot trajectory across the Feb 28 P1/P2 transition."""
    traj = pd.read_csv(OUTPUTS_DIR / "p1_p2_transition_snapshot_trajectory.csv")
    fig, ax = plt.subplots(figsize=(4.4, 2.8))
    ax.plot(_ts_to_dt(traj["ts"]), traj["dark_share"] * 100, marker="o",
            color=CATEGORICAL[5], label="announced but dark")
    ax.plot(_ts_to_dt(traj["ts"]), traj["withdrawn_share"] * 100, marker="o",
            color=CATEGORICAL[0], label="withdrawn from routing")
    ax.set_ylabel("share of networks (%)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d, %H:%M"))
    fig.autofmt_xdate(rotation=30)
    ax.legend(fontsize=7)
    clean_axes(ax)
    fig.tight_layout()
    savefig(fig, "transition_zoom")
    plt.close(fig)


_BUILDERS = {
    "timeline": fig_timeline,
    "state_share": fig_state_share,
    "control_falsification": fig_control_falsification,
    "h2_churn": fig_h2_churn,
    "h3_visibility_by_type": fig_h3_visibility_by_type,
    "h3_restoration_speed": fig_h3_restoration_speed,
    "h4_comparison": fig_h4_comparison,
    "bimodality": fig_bimodality,
    "transition_zoom": fig_transition_zoom,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=FIGURES, help="build a single figure")
    ap.add_argument("--config-dir", default=CONFIG_DIR)
    args = ap.parse_args()

    apply_style()
    cfg = Config.load(args.config_dir)
    names = [args.only] if args.only else FIGURES
    for name in names:
        _BUILDERS[name](cfg)
        log.info("built %s", name)


if __name__ == "__main__":
    main()
