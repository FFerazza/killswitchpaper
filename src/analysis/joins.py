"""Stage 5: joined, figure-ready analysis tables (no figures here).

Inputs: Stage 1 classification, Stage 2 visibility/events, Stage 3 IODA.
Outputs (all under outputs/):
    visibility_by_type.parquet     (H3)
    bgp_vs_ioda.parquet            (H1)
    upstream_transitions.parquet   (H2)
    event_speed.parquet            (H4)
    restoration_events.parquet     (H3 centerpiece, D-023)
    fine_restoration_order.parquet (H3, event-stream resolution companion)
    restoration_order_by_type.parquet (H3, event-stream resolution companion)
"""

from pathlib import Path

import pandas as pd

from src.common.log import get_logger
from src.common.rollup import map_to_blocks, rollup_visibility
from src.analysis.flap_gaps import drop_flap_withdrawals
from src.analysis.states import derive_state

log = get_logger("analysis.joins")

_PROBING_SIGNAL = "ping-slash24"


def drop_degraded(df: pd.DataFrame, min_fullfeed_peers: int) -> pd.DataFrame:
    """D-020: drop (snapshot, family) cells with too few full-feed peers.

    peers_total is the row's own-family full-feed count, so the row-level
    comparison excludes exactly the degraded family at that snapshot while
    keeping the other family's rows.
    """
    degraded = df["peers_total"] < min_fullfeed_peers
    if degraded.any():
        cells = df.loc[degraded, ["ts", "family"]].drop_duplicates()
        log.warning("D-020: dropping %d degraded (snapshot, family) cells: %s",
                    len(cells),
                    [(int(r.ts), int(r.family)) for r in cells.itertuples()])
        df = df[~degraded]
    return df


def write_parquet(df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(out_path)
    log.info("%d rows -> %s", len(df), out_path)


def visibility_by_type(
    visibility: pd.DataFrame, classification: pd.DataFrame, out_path: Path
) -> pd.DataFrame:
    """H3: mean visibility fraction over time, aggregated by classification type."""
    cls = classification[["asn", "type"]].copy()
    cls["type"] = cls["type"].fillna("").replace("", "unclassified")
    df = visibility.merge(cls, left_on="origin_asn", right_on="asn", how="left")
    df["type"] = df["type"].fillna("unclassified")
    agg = (
        df.groupby(["ts", "type"])
        .agg(visibility_mean=("visibility", "mean"),
             visibility_median=("visibility", "median"),
             n_prefixes=("prefix", "nunique"))
        .reset_index()
    )
    write_parquet(agg, out_path)
    return agg


def restoration_by_type(
    restoration: pd.DataFrame, classification: pd.DataFrame, p4_start: int, out_path: Path
) -> pd.DataFrame:
    """H3 centerpiece: D-023 restoration timing/completeness by ASN classification
    type - the selectivity question (do gov/banking/state-media prefixes come
    back earlier and more completely than consumer/mobile ones?).

    Blocks that never cross the primary threshold by the end of the study
    period are counted in `n_never_restored`, not silently dropped - "still
    dark at the end of the study period" is itself an H3-relevant finding,
    and dropping them would bias `median_delay_s` toward only the ASNs that
    did recover.
    """
    cls = classification[["asn", "type"]].copy()
    cls["type"] = cls["type"].fillna("").replace("", "unclassified")
    df = restoration.merge(cls, on="asn", how="left")
    df["type"] = df["type"].fillna("unclassified")
    df["delay_to_restoration_s"] = df["restoration_ts"] - p4_start
    agg = (
        df.groupby("type")
        .agg(
            n_blocks=("prefix", "nunique"),
            n_restored=("restoration_ts", "count"),
            median_delay_s=("delay_to_restoration_s", "median"),
            mean_delay_s=("delay_to_restoration_s", "mean"),
            median_steady_state_ratio=("steady_state_ratio", "median"),
        )
        .reset_index()
    )
    agg["n_never_restored"] = agg["n_blocks"] - agg["n_restored"]
    write_parquet(agg, out_path)
    return agg


def _per_as_visibility(visibility: pd.DataFrame) -> pd.DataFrame:
    """Collapse per-prefix visibility to per-AS: max visibility across prefixes."""
    return (
        visibility.groupby(["ts", "origin_asn"])["visibility"]
        .max()
        .reset_index()
        .rename(columns={"origin_asn": "asn"})
    )


def _probing_baseline(
    baseline_dir: Path, asn: int, min_nonzero_share: float, min_median: float
) -> tuple[float | None, bool, dict]:
    """D-013 (D-005): per-AS baseline = median probing over the fixed P0 reference
    window; the AS is probing-adequate only if the window has enough signal.

    Returns (baseline or None, adequate, stats-for-exclusion-table).
    """
    path = baseline_dir / f"{asn}.parquet"
    stats = {"asn": asn, "nonzero_share": None, "median": None}
    if not path.exists():
        return None, False, stats
    sig = pd.read_parquet(path)
    values = sig[sig["datasource"] == _PROBING_SIGNAL]["value"].dropna()
    if values.empty:
        return None, False, stats
    nonzero_share = float((values > 0).mean())
    median = float(values.median())
    stats.update(nonzero_share=round(nonzero_share, 4), median=median)
    adequate = nonzero_share >= min_nonzero_share and median >= min_median
    return (median if adequate else None), adequate, stats


def bgp_vs_ioda(
    visibility: pd.DataFrame,
    ioda_asn_dir: Path,
    ioda_baseline_dir: Path,
    visibility_announced_min: float,
    probing_dark_ratio: float,
    probing_adequacy: dict,
    out_path: Path,
    excluded_out_path: Path | None = None,
) -> pd.DataFrame:
    """H1: align BGP visibility with IODA probing per AS, derive state per snapshot.

    IODA probing values are matched to each RIB snapshot with a nearest-
    backward join (asof); the probing baseline follows D-013: the AS's median
    signal over the fixed P0 reference window (read from `ioda_baseline_dir`),
    with the adequacy rule deciding whether the AS enters probing-based
    metrics at all. Inadequate ASes stay in the output flagged
    probing_adequate=False (BGP-only interpretation) and are listed in
    `excluded_out_path`.

    Each AS is reindexed over the full snapshot grid with visibility 0 for
    snapshots where none of its prefixes appear: a fully withdrawn AS has no
    RIB rows at all, and those gaps ARE the `withdrawn` state (H1).
    """
    per_as = _per_as_visibility(visibility)
    excluded_rows = []
    all_ts = sorted(visibility["ts"].unique())
    frames = []
    for asn, group in per_as.groupby("asn"):
        group = (
            group.set_index("ts")
            .reindex(all_ts)
            .assign(asn=asn)
            .fillna({"visibility": 0.0})
            .reset_index(names="ts")
        )
        ioda_path = ioda_asn_dir / f"{int(asn)}.parquet"
        probing = None
        if ioda_path.exists():
            sig = pd.read_parquet(ioda_path)
            sig = sig[sig["datasource"] == _PROBING_SIGNAL].dropna(subset=["value"])
            if not sig.empty:
                probing = sig.sort_values("ts")
        group = group.sort_values("ts").copy()
        if probing is not None:
            merged = pd.merge_asof(
                group, probing[["ts", "value"]].rename(columns={"value": "probing"}),
                on="ts", direction="backward",
            )
        else:
            merged = group.assign(probing=None)
        baseline, adequate, stats = _probing_baseline(
            ioda_baseline_dir, int(asn),
            probing_adequacy["min_nonzero_share"], probing_adequacy["min_median"],
        )
        if not adequate:
            excluded_rows.append(stats)
        merged["probing_baseline"] = baseline
        merged["probing_adequate"] = adequate
        merged["state"] = [
            derive_state(
                row.visibility,
                None if pd.isna(row.probing) else float(row.probing),
                baseline,
                visibility_announced_min,
                probing_dark_ratio,
            )
            for row in merged.itertuples()
        ]
        frames.append(merged)
    result = pd.concat(frames, ignore_index=True)
    write_parquet(result, out_path)
    if excluded_out_path is not None:
        excl = pd.DataFrame(excluded_rows, columns=["asn", "nonzero_share", "median"])
        excluded_out_path.parent.mkdir(parents=True, exist_ok=True)
        excl.to_csv(excluded_out_path, index=False)
        log.info("%d probing-inadequate ASNs (D-013 exclusion list) -> %s",
                 len(excl), excluded_out_path)
    return result


def upstream_transitions(visibility: pd.DataFrame, out_path: Path) -> pd.DataFrame:
    """H2: per-AS upstream sets over time from AS paths; flag set changes."""
    df = visibility[visibility["origin_asn"] > 0].copy()

    def _union(series: pd.Series) -> str:
        merged: set[str] = set()
        for s in series:
            if s:
                merged.update(s.split(","))
        return ",".join(sorted(merged, key=int))

    per_as = (
        df.groupby(["ts", "origin_asn"])["upstreams"]
        .apply(_union)
        .reset_index()
        .rename(columns={"origin_asn": "asn"})
        .sort_values(["asn", "ts"])
    )
    per_as["prev_upstreams"] = per_as.groupby("asn")["upstreams"].shift()
    per_as["changed"] = per_as["prev_upstreams"].notna() & (
        per_as["upstreams"] != per_as["prev_upstreams"]
    )
    per_as["n_upstreams"] = per_as["upstreams"].apply(lambda s: len(s.split(",")) if s else 0)
    write_parquet(per_as, out_path)
    return per_as


def event_speed(
    events_dir: Path, out_path: Path, flap_threshold_s: int | None = None
) -> pd.DataFrame:
    """H4: onset duration per event window.

    D-024: primary cross-window metric is duration_p5_p95_s, the
    interpercentile range (t_p95 - t_p5) of per-prefix first-withdrawal
    times - robust to the single-straggler-prefix problem that makes the
    full range (duration_s, still reported for context) misleading across
    windows of very different length. duration_p50/p90/p99_s are elapsed
    time FROM t_first TO that percentile (a different question - "how long
    to reach the Nth percentile of the wave" - kept as secondary stats, not
    a substitute for the range).

    D-009: if `flap_threshold_s` is given, withdraw rows whose same peer
    session reannounces within that many seconds are dropped before finding
    each prefix's first withdrawal - a flap is not a meaningful onset event.
    None (default) preserves pre-D-009 behavior (no flap filtering).
    """
    rows = []
    for path in sorted(events_dir.glob("*.parquet")):
        window = path.stem
        events = pd.read_parquet(path)
        # Onset duration is an IR metric; windows pulled before D-016 carry
        # no cc column and are IR-only by construction.
        if "cc" in events.columns:
            events = events[events["cc"] == "IR"]
        if flap_threshold_s is not None:
            events = drop_flap_withdrawals(events, flap_threshold_s)
        withdrawals = events[events["event"] == "withdraw"]
        if withdrawals.empty:
            log.warning("window %s: no withdrawals", window)
            continue
        first_w = withdrawals.groupby("prefix")["ts"].min()
        p5, p95 = first_w.quantile(0.05), first_w.quantile(0.95)
        rows.append({
            "window": window,
            "n_prefixes_withdrawn": int(first_w.size),
            "t_first": int(first_w.min()),
            "t_last": int(first_w.max()),
            "duration_s": int(first_w.max() - first_w.min()),
            "duration_p5_p95_s": int(p95 - p5),
            "duration_p50_s": int(first_w.quantile(0.50) - first_w.min()),
            "duration_p90_s": int(first_w.quantile(0.90) - first_w.min()),
            "duration_p99_s": int(first_w.quantile(0.99) - first_w.min()),
        })
    df = pd.DataFrame(rows)
    write_parquet(df, out_path)
    return df


def _dominant_asn(visibility: pd.DataFrame, delegated: pd.DataFrame) -> pd.Series:
    """Each delegated block's owning ASN: the most-frequently observed
    origin_asn among the observed prefixes that map into it (mode across
    all snapshots) - a block's origin is stable in practice but this is
    robust to the rare reannounce-from-a-different-origin snapshot."""
    mapping = map_to_blocks(visibility["prefix"].unique(), delegated["prefix"])
    df = visibility[["prefix", "origin_asn"]].copy()
    df["block"] = df["prefix"].map(mapping)
    return df.groupby("block")["origin_asn"].agg(lambda s: s.mode().iat[0])


def restoration_events(
    visibility: pd.DataFrame,
    delegated: pd.DataFrame,
    p0_start: int,
    p0_end: int,
    p4_start: int,
    steady_state_start: int,
    thresholds: list[float],
    primary_threshold: float,
    out_path: Path,
) -> pd.DataFrame:
    """D-023 (H3 centerpiece): per-delegated-block restoration timing.

    Restoration timestamp = first ts >= p4_start where the block's D-022
    address-space-weighted visibility re-crosses `primary_threshold` (0.5)
    of the block's own P0 baseline mean; `thresholds` (0.25/0.5/0.8) are
    computed alongside as pre-committed robustness companions, never
    substituted for the primary. Steady-state visibility (mean over the
    final study month, `steady_state_start` onward) and its ratio to the P0
    baseline are reported as a separate completeness metric - timing and
    completeness are different H3 questions (D-023) and must not collapse
    into one number.

    A block absent from a given ts in the rollup had zero observed
    announcements there (fully withdrawn, D-016/H1 convention) - reindexed
    to the full snapshot grid with visibility 0 before computing means/
    crossings, so a silent gap can't read as "never measured."
    """
    rolled = rollup_visibility(visibility, delegated)
    asn = _dominant_asn(visibility, delegated)
    all_ts = sorted(rolled["ts"].unique())

    rows = []
    n_no_baseline = 0
    for block, group in rolled.groupby("prefix"):
        family = group["family"].iloc[0]
        series = (
            group.set_index("ts")["visibility_weighted"]
            .reindex(all_ts, fill_value=0.0)
        )
        p0 = series[(series.index >= p0_start) & (series.index < p0_end)]
        baseline_mean = float(p0.mean()) if not p0.empty else None
        row = {
            "prefix": block, "family": int(family),
            "asn": int(asn.get(block, -1)),
            "p0_baseline_mean": baseline_mean,
        }
        usable_baseline = baseline_mean is not None and baseline_mean > 0
        if not usable_baseline:
            n_no_baseline += 1
        post_p4 = series[series.index >= p4_start]
        for t in thresholds:
            col = f"restoration_ts_p{int(round(t * 100))}"
            if not usable_baseline:
                row[col] = None
                continue
            crossed = post_p4[post_p4 >= t * baseline_mean]
            row[col] = int(crossed.index[0]) if not crossed.empty else None
        row["restoration_ts"] = row[f"restoration_ts_p{int(round(primary_threshold * 100))}"]
        steady = series[series.index >= steady_state_start]
        steady_mean = float(steady.mean()) if not steady.empty else None
        row["steady_state_visibility"] = steady_mean
        row["steady_state_ratio"] = (
            steady_mean / baseline_mean if usable_baseline and steady_mean is not None else None
        )
        rows.append(row)

    df = pd.DataFrame(rows)
    if n_no_baseline:
        log.warning(
            "D-023: %d/%d delegated blocks have no usable P0 baseline "
            "(never observed, or always zero, in P0) - restoration timing "
            "undefined for them", n_no_baseline, len(df),
        )
    write_parquet(df, out_path)
    return df


def fine_restoration_order(
    events: pd.DataFrame, delegated: pd.DataFrame, since_ts: int, out_path: Path
) -> pd.DataFrame:
    """H3 companion to `restoration_events` (D-023): first reannouncement
    time per delegated block AFTER `since_ts` (the P4 boundary - same
    reference point as `restoration_events`' "first ts after P4" so the two
    are directly comparable), at raw BGP-update-stream resolution.

    D-023's restoration_ts (a visibility-fraction threshold crossing on the
    8h primary RIB-snapshot series) turned out to have essentially no
    within-window resolution for the May 2026 restoration: ~97% of blocks
    cross 50% of their own P0 baseline at the very first post-P4 snapshot,
    because the true crossing happens somewhere inside that 8h gap and the
    snapshot grid can't see where. This uses the `may2026_restoration` raw
    update stream (real event timestamps, not an 8h grid) instead: for each
    block, the ts of its first `announce` event for any covered prefix.

    The pulled event window starts ~2.5 days before the P4 boundary (margin
    for the boundary-detection uncertainty) - filtering to ts >= since_ts is
    required, not optional: without it, "first announce in the whole window"
    just picks up ordinary pre-restoration routing activity from inside that
    margin (verified on real data - every block's unfiltered first-announce
    landed within minutes of the window's own start, ~55-60h before the P4
    boundary, clearly not the restoration moment).

    This is a genuinely different, simpler metric (first reannouncement,
    not a visibility-fraction threshold) - reported alongside restoration_ts,
    never substituted for it. Flap noise is not filtered (D-009, the flap
    definition, is still an OPEN decision) - same caveat that already
    applies to `event_speed`'s withdrawal times.
    """
    ir = events[
        (events["cc"] == "IR") & (events["event"] == "announce") & (events["ts"] >= since_ts)
    ]
    mapping = map_to_blocks(ir["prefix"].unique(), delegated["prefix"])
    df = ir.assign(block=ir["prefix"].map(mapping))
    result = (
        df.groupby("block")["ts"].min()
        .rename("first_reannounce_ts")
        .reset_index()
        .rename(columns={"block": "prefix"})
    )
    write_parquet(result, out_path)
    return result


def restoration_order_by_type(
    fine_order: pd.DataFrame,
    restoration: pd.DataFrame,
    classification: pd.DataFrame,
    window_start: int,
    out_path: Path,
) -> pd.DataFrame:
    """H3 (event-stream-resolution companion): first-reannouncement delay by
    ASN type, using `fine_restoration_order`'s timing joined to the per-block
    ASN attribution `restoration_events` already computed. `window_start`
    should be the same P4 boundary `restoration_events` measures delay from,
    so `delay_s` here is directly comparable to its `delay_to_restoration_s`.
    """
    df = fine_order.merge(restoration[["prefix", "asn"]], on="prefix", how="left")
    cls = classification[["asn", "type"]].copy()
    cls["type"] = cls["type"].fillna("").replace("", "unclassified")
    df = df.merge(cls, on="asn", how="left")
    df["type"] = df["type"].fillna("unclassified")
    df["delay_s"] = df["first_reannounce_ts"] - window_start
    agg = (
        df.groupby("type")
        .agg(
            n_blocks=("prefix", "nunique"),
            median_delay_s=("delay_s", "median"),
            mean_delay_s=("delay_s", "mean"),
            p10_delay_s=("delay_s", lambda s: s.quantile(0.10)),
            p90_delay_s=("delay_s", lambda s: s.quantile(0.90)),
        )
        .reset_index()
    )
    write_parquet(agg, out_path)
    return agg
