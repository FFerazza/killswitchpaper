"""QC scan of per-entity IODA pulls (data/ioda/{asn,country_IR.parquet}).

Verifies, per entity file:
  - the parquet is readable with the expected columns,
  - no duplicate (ts, datasource) rows (the chunk-boundary dedupe in
    src/ioda/client.py should already guarantee this - a regression here means
    the dedupe broke),
  - per datasource, the time grid is on its own native step with no
    unexplained gaps (each signal has its own native step - e.g. bgp/merit-nt
    empirically run 300s, ping-slash24 600s; this is discovered per file, not
    assumed, since a hardcoded expectation would be exactly the kind of
    silently-picked constant CLAUDE.md warns against),
  - coverage span matches the requested window (min ts == start, max ts ==
    end - step, for a half-open [start, end) query).

Entities with zero rows for a datasource are not flagged (many ASNs
legitimately have no darknet/probing traffic); this is operational QC, not an
analytical exclusion rule - nothing is dropped, problems are printed for
human review.

Optionally cross-checks against an earlier trusted pull (e.g.
data/ioda/testweek/) over their overlapping timestamps: same entity, same
datasource, same ts must give the same value, since these are queries for
historical (already-settled) data and should be deterministic.

Usage:
    python -m src.analysis.ioda_health data/ioda --start ISO --end ISO
    python -m src.analysis.ioda_health data/ioda --start ISO --end ISO \\
        --compare data/ioda/testweek
"""

import argparse
from pathlib import Path

import pandas as pd

from src.common.log import get_logger
from src.common.timeutil import to_iso, to_unix

log = get_logger("analysis.ioda_health")

_EXPECTED_COLUMNS = {"ts", "entity_type", "entity_code", "datasource", "value"}


def scan_file(path: Path, start: int, end: int) -> tuple[dict, list[str]]:
    """Return (metrics, problems) for one entity parquet."""
    problems: list[str] = []
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        return {"rows": 0}, [f"unreadable parquet: {e}"]

    missing_cols = _EXPECTED_COLUMNS - set(df.columns)
    if missing_cols:
        return {"rows": len(df)}, [f"missing columns: {sorted(missing_cols)}"]

    dup = df.duplicated(subset=["ts", "datasource"])
    if dup.any():
        problems.append(f"{int(dup.sum())} duplicate (ts, datasource) row(s)")

    per_ds_steps: dict[str, int] = {}
    for ds, g in df.groupby("datasource"):
        g = g.sort_values("ts")
        if len(g) < 2:
            continue
        diffs = g["ts"].diff().dropna()
        step = int(diffs.mode().iloc[0])
        per_ds_steps[ds] = step
        bad = diffs[(diffs % step != 0) | (diffs <= 0)]
        if not bad.empty:
            problems.append(f"{ds}: {len(bad)} irregular step(s) (native step {step}s)")
        if g["ts"].min() != start:
            problems.append(f"{ds}: coverage starts {to_iso(int(g['ts'].min()))}, expected {to_iso(start)}")
        expected_last = end - step
        if g["ts"].max() != expected_last:
            problems.append(
                f"{ds}: coverage ends {to_iso(int(g['ts'].max()))}, "
                f"expected {to_iso(expected_last)} (end - native step)"
            )

    metrics = {
        "rows": len(df),
        "datasources": sorted(per_ds_steps),
        "steps": per_ds_steps,
    }
    return metrics, problems


def cross_check(path: Path, compare_path: Path) -> list[str]:
    """Compare overlapping (ts, datasource) values against a trusted prior pull."""
    df = pd.read_parquet(path)
    other = pd.read_parquet(compare_path)
    merged = df.merge(other, on=["ts", "datasource"], suffixes=("", "_ref"), how="inner")
    if merged.empty:
        return []
    value = merged["value"].astype("float64")
    value_ref = merged["value_ref"].astype("float64")
    both_null = value.isna() & value_ref.isna()
    close = value.sub(value_ref).abs().le(1e-6)
    mismatched = merged[~both_null & ~close.fillna(False)]
    if mismatched.empty:
        return []
    return [
        f"{len(mismatched)}/{len(merged)} overlapping row(s) disagree with {compare_path.parent.name}"
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ioda_dir", type=Path, help="e.g. data/ioda")
    ap.add_argument("--start", required=True, help="ISO 8601 start of the pulled window")
    ap.add_argument("--end", required=True, help="ISO 8601 end of the pulled window")
    ap.add_argument("--compare", type=Path, default=None,
                    help="another ioda dir (e.g. data/ioda/testweek) to cross-check "
                         "overlapping timestamps against")
    args = ap.parse_args()

    start, end = to_unix(args.start), to_unix(args.end)
    paths = sorted((args.ioda_dir / "asn").glob("*.parquet"))
    country = args.ioda_dir / "country_IR.parquet"
    if country.exists():
        paths.append(country)
    if not paths:
        raise SystemExit(f"no entity parquets under {args.ioda_dir}")

    problems_by_file: dict[str, list[str]] = {}
    empty = 0
    total_rows = 0
    for p in paths:
        metrics, problems = scan_file(p, start, end)
        total_rows += metrics.get("rows", 0)
        if metrics.get("rows", 0) == 0:
            empty += 1
        if problems:
            problems_by_file[p.stem] = problems
        if args.compare:
            compare_path = (
                args.compare / "country_IR.parquet" if p == country
                else args.compare / "asn" / p.name
            )
            if compare_path.exists():
                cross_problems = cross_check(p, compare_path)
                if cross_problems:
                    problems_by_file.setdefault(p.stem, []).extend(cross_problems)

    print(f"{len(paths)} entities in {args.ioda_dir} ({total_rows} total rows, "
          f"{empty} with zero rows)")
    if problems_by_file:
        print(f"\nPROBLEMS in {len(problems_by_file)} entit(y/ies):")
        for name, probs in sorted(problems_by_file.items()):
            for prob in probs:
                print(f"  {name}: {prob}")
        raise SystemExit(1)
    print("\nall entities healthy")


if __name__ == "__main__":
    main()
