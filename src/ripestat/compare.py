"""Compare RIPEstat routing history against the pipeline's visibility series.

For each sampled ASN and each RIB snapshot time, RIPEstat says whether the
ASN originated any prefix (a routing-history period covering that time);
the pipeline says whether any prefix with that origin had visibility above
threshold. Disagreements are flagged for manual inspection — this validates
Stage 2 before trusting a full-period run (Milestone 1).
"""

import json
from pathlib import Path

import pandas as pd

from src.common.log import get_logger
from src.common.timeutil import to_iso, to_unix

log = get_logger("ripestat.compare")


def ripestat_active_periods(doc: dict) -> list[tuple[int, int]]:
    """Extract (start, end) unix periods when the ASN originated prefixes."""
    periods = []
    for entry in doc.get("data", {}).get("by_origin", []):
        for prefix_block in entry.get("prefixes", []):
            for timeline in prefix_block.get("timelines", []):
                start = to_unix(timeline["starttime"])
                end = to_unix(timeline["endtime"])
                periods.append((start, end))
    return periods


def asn_active_at(periods: list[tuple[int, int]], ts: int) -> bool:
    return any(start <= ts <= end for start, end in periods)


def compare_asn(
    asn: int,
    ripestat_path: Path,
    visibility: pd.DataFrame,
    vis_threshold: float,
) -> pd.DataFrame:
    """Return one row per snapshot with both verdicts and an `agree` flag."""
    with open(ripestat_path) as f:
        doc = json.load(f)
    periods = ripestat_active_periods(doc)

    ours = visibility[visibility["origin_asn"] == asn]
    rows = []
    for ts, group in ours.groupby("ts"):
        pipeline_visible = bool((group["visibility"] >= vis_threshold).any())
        ripestat_visible = asn_active_at(periods, int(ts))
        rows.append({
            "asn": asn,
            "ts": int(ts),
            "iso": to_iso(int(ts)),
            "pipeline_visible": pipeline_visible,
            "ripestat_visible": ripestat_visible,
            "agree": pipeline_visible == ripestat_visible,
        })
    return pd.DataFrame(rows)


def run_comparison(
    asns: list[int],
    ripestat_dir: Path,
    visibility_path: Path,
    vis_threshold: float,
) -> pd.DataFrame:
    if not visibility_path.exists():
        raise SystemExit(f"{visibility_path} not found - run `make bgp-ribs` (or test-week) first")
    visibility = pd.read_parquet(visibility_path)
    frames = []
    for asn in asns:
        path = ripestat_dir / f"{asn}.json"
        if not path.exists():
            log.warning("no RIPEstat file for AS%d (%s missing); skipping", asn, path)
            continue
        frames.append(compare_asn(asn, path, visibility, vis_threshold))
    if not frames:
        raise SystemExit("nothing to compare - fetch RIPEstat data first")
    result = pd.concat(frames, ignore_index=True)
    for asn, group in result.groupby("asn"):
        n_disagree = int((~group["agree"]).sum())
        level = log.warning if n_disagree else log.info
        level("AS%d: %d/%d snapshots agree (%d disagreements)",
              asn, int(group["agree"].sum()), len(group), n_disagree)
    return result
