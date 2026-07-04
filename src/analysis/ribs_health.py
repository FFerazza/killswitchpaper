"""QC scan of RIB snapshot parquets (primary or RIS-backfill series).

Verifies, per snapshot file:
  - the parquet is readable and non-empty (a crash mid-write would fail here),
  - the ts column is uniform and matches the filename,
  - every expected collector appears in the collector_fullfeed audit column,
  - peer totals and full-feed counts are stable across snapshots (the D-002
    contamination signature was a jump in exactly these numbers).

Peer/full-feed instability is flagged relative to the series median; IR
prefix counts are reported but never flagged, since they legitimately
collapse during shutdown windows. This is operational QC, not an analytical
exclusion rule: nothing is dropped, anomalies are printed for human review.

Usage: python -m src.analysis.ribs_health data/bgp/ribs_ris \
           --collectors route-views2 route-views.linx rrc00 rrc12
"""

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

# Flag-only tolerance for peer/full-feed drift around the series median.
# Generous on purpose: real contamination moved these by ~2x (118->217 peers).
_DRIFT_FRAC = 0.15


def scan_file(path: Path, expected_collectors: set[str]) -> tuple[dict, list[str]]:
    """Return (metrics, problems) for one snapshot parquet."""
    problems: list[str] = []
    name_ts = int(path.stem.split("_")[1])
    try:
        t = pq.read_table(
            path, columns=["ts", "family", "peers_total", "collector_fullfeed", "prefix"]
        )
    except Exception as e:
        return {"ts": name_ts}, [f"unreadable parquet: {e}"]

    if t.num_rows == 0:
        return {"ts": name_ts}, ["empty parquet"]

    ts_vals = t.column("ts").unique().to_pylist()
    if ts_vals != [name_ts]:
        problems.append(f"ts column {ts_vals} != filename ts {name_ts}")

    ff_vals = t.column("collector_fullfeed").unique().to_pylist()
    if len(ff_vals) != 1:
        problems.append(f"{len(ff_vals)} distinct collector_fullfeed values in one snapshot")
    ff = json.loads(ff_vals[0])

    missing = expected_collectors - set(ff)
    if missing:
        problems.append(f"missing collectors: {sorted(missing)}")

    # peers_total is the per-family visibility denominator: it must be uniform
    # within each family and equal the summed full-feed count of the audit column.
    df = t.select(["family", "peers_total"]).to_pandas()
    peers_by_family = {}
    fam_key = {4: "ipv4", 6: "ipv6"}
    for fam, vals in df.groupby("family")["peers_total"].unique().items():
        if len(vals) != 1:
            problems.append(f"non-uniform peers_total within family {fam}: {sorted(vals)}")
        peers_by_family[fam] = vals[0]
        ff_sum = sum(v.get(fam_key[fam], 0) for v in ff.values())
        if vals[0] != ff_sum:
            problems.append(
                f"family {fam} peers_total {vals[0]} != collector_fullfeed sum {ff_sum}"
            )

    metrics = {
        "ts": name_ts,
        "rows": t.num_rows,
        "prefixes": len(t.column("prefix").unique()),
        "ff_v4": peers_by_family.get(4, 0),
        "ff_v6": peers_by_family.get(6, 0),
    }
    return metrics, problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ribs_dir", type=Path)
    ap.add_argument("--collectors", nargs="+", required=True,
                    help="collectors every snapshot must contain")
    args = ap.parse_args()

    paths = sorted(args.ribs_dir.glob("rib_*.parquet"))
    if not paths:
        raise SystemExit(f"no rib_*.parquet in {args.ribs_dir}")
    expected = set(args.collectors)

    results = []
    problems_by_file: dict[str, list[str]] = {}
    for p in paths:
        metrics, problems = scan_file(p, expected)
        results.append(metrics)
        if problems:
            problems_by_file[p.name] = problems

    healthy = [r for r in results if "ff_v4" in r]
    for key in ("ff_v4", "ff_v6"):
        med = statistics.median(r[key] for r in healthy)
        for r in healthy:
            if abs(r[key] - med) > _DRIFT_FRAC * med:
                name = f"rib_{r['ts']}.parquet"
                problems_by_file.setdefault(name, []).append(
                    f"{key}={r[key]} drifts >{_DRIFT_FRAC:.0%} from series median {med}"
                )

    def iso(ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M")

    print(f"{len(paths)} snapshots in {args.ribs_dir}")
    for key in ("ff_v4", "ff_v6", "prefixes"):
        vals = [r[key] for r in healthy if key in r]
        print(f"  {key}: min={min(vals)} median={statistics.median(vals)} max={max(vals)}")

    # 8h-grid gaps inside the covered span are expected between disjoint
    # backfill ranges; print them so coverage is explicit, but don't flag.
    ts_sorted = sorted(r["ts"] for r in results)
    gaps = [(a, b) for a, b in zip(ts_sorted, ts_sorted[1:]) if b - a > 8 * 3600]
    if gaps:
        print(f"  {len(gaps)} gaps >8h (range boundaries or missing snapshots):")
        for a, b in gaps:
            print(f"    {iso(a)} -> {iso(b)}")

    if problems_by_file:
        print(f"\nPROBLEMS in {len(problems_by_file)} file(s):")
        for name, probs in sorted(problems_by_file.items()):
            for prob in probs:
                print(f"  {name}: {prob}")
        raise SystemExit(1)
    print("\nall snapshots healthy")


if __name__ == "__main__":
    main()
