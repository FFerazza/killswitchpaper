"""Stage 5: joined, figure-ready analysis tables (no figures here).

Inputs: Stage 1 classification, Stage 2 visibility/events, Stage 3 IODA.
Outputs (all under outputs/):
    visibility_by_type.parquet     (H3)
    bgp_vs_ioda.parquet            (H1)
    upstream_transitions.parquet   (H2)
    event_speed.parquet            (H4)
"""

from pathlib import Path

import pandas as pd

from src.common.log import get_logger
from src.analysis.states import derive_state

log = get_logger("analysis.joins")

_PROBING_SIGNAL = "ping-slash24"


def _write(df: pd.DataFrame, out_path: Path) -> None:
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
    _write(agg, out_path)
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
    _write(result, out_path)
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
    _write(per_as, out_path)
    return per_as


def event_speed(events_dir: Path, out_path: Path) -> pd.DataFrame:
    """H4: onset duration per event window - time from first to last withdrawal.

    Uses per-prefix first-withdrawal times so a long tail of BGP chatter does
    not inflate the duration: reported spread percentiles cover the bulk of
    the withdrawal wave.
    """
    rows = []
    for path in sorted(events_dir.glob("*.parquet")):
        window = path.stem
        events = pd.read_parquet(path)
        # Onset duration is an IR metric; windows pulled before D-016 carry
        # no cc column and are IR-only by construction.
        if "cc" in events.columns:
            events = events[events["cc"] == "IR"]
        withdrawals = events[events["event"] == "withdraw"]
        if withdrawals.empty:
            log.warning("window %s: no withdrawals", window)
            continue
        first_w = withdrawals.groupby("prefix")["ts"].min()
        rows.append({
            "window": window,
            "n_prefixes_withdrawn": int(first_w.size),
            "t_first": int(first_w.min()),
            "t_last": int(first_w.max()),
            "duration_s": int(first_w.max() - first_w.min()),
            "duration_p50_s": int(first_w.quantile(0.50) - first_w.min()),
            "duration_p90_s": int(first_w.quantile(0.90) - first_w.min()),
            "duration_p99_s": int(first_w.quantile(0.99) - first_w.min()),
        })
    df = pd.DataFrame(rows)
    _write(df, out_path)
    return df
