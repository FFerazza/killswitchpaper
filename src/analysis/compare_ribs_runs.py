"""Cross-validate two RIB snapshot series over the same window (D-016 gate).

Motivation: Stage 2 population tagging (D-016) changed the snapshot schema
(new `cc` column, control prefixes matched alongside IR). The tagging must be
purely additive: on IR rows, a D-016 run over the same window and collectors
must reproduce the pre-D-016 run exactly, because both read the same immutable
archive dumps. Any numeric drift on IR rows means the change altered
measurement, not just labeling.

Per common snapshot:
  - collector_fullfeed audit strings must be identical (same peers, same
    full-feed counts -> same visibility denominator),
  - the IR prefix sets must be identical,
  - peers_seen / peers_total / visibility / origin_asn must be equal
    prefix-by-prefix on IR rows,
  - candidate-only population tags (cc != IR) are reported per country as a
    sanity readout, never compared (the baseline could not see them).

Baseline rows have no cc column (or NaN cc): pre-D-016 files matched only the
IR population, so all their rows are IR by construction. This is operational
QC, not an analytical rule: nothing is dropped, mismatches are printed and the
exit status is nonzero for human review.

Usage: python -m src.analysis.compare_ribs_runs data/bgp/ribs \
           data/bgp/ribs_ec2_testweek
"""

import argparse
from pathlib import Path

import pandas as pd

_COMPARE_COLS = ["peers_seen", "peers_total", "visibility", "origin_asn"]


def ir_rows(df: pd.DataFrame) -> pd.DataFrame:
    if "cc" not in df.columns:
        return df
    return df[df["cc"].isna() | (df["cc"] == "IR")]


def compare_snapshot(base: pd.DataFrame, cand: pd.DataFrame) -> list[str]:
    """Return mismatch descriptions for one snapshot pair (empty = identical)."""
    problems: list[str] = []

    base_audit = base["collector_fullfeed"].unique().tolist()
    cand_audit = cand["collector_fullfeed"].unique().tolist()
    if base_audit != cand_audit:
        problems.append(f"collector_fullfeed differs: {base_audit} vs {cand_audit}")

    base_ir = ir_rows(base)
    cand_ir = ir_rows(cand)
    base_set = set(base_ir["prefix"])
    cand_set = set(cand_ir["prefix"])
    if base_set != cand_set:
        only_base = sorted(base_set - cand_set)[:5]
        only_cand = sorted(cand_set - base_set)[:5]
        problems.append(
            f"IR prefix sets differ: {len(base_set - cand_set)} only-baseline "
            f"(e.g. {only_base}), {len(cand_set - base_set)} only-candidate "
            f"(e.g. {only_cand})"
        )

    merged = base_ir.merge(cand_ir, on="prefix", suffixes=("_b", "_c"))
    for col in _COMPARE_COLS:
        neq = merged[merged[f"{col}_b"] != merged[f"{col}_c"]]
        if len(neq):
            ex = neq.iloc[0]
            problems.append(
                f"{col} differs on {len(neq)}/{len(merged)} IR prefixes "
                f"(e.g. {ex['prefix']}: {ex[f'{col}_b']} vs {ex[f'{col}_c']})"
            )
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline_dir", type=Path, help="pre-D-016 snapshot dir")
    ap.add_argument("candidate_dir", type=Path, help="D-016-tagged snapshot dir")
    args = ap.parse_args()

    base_files = {p.name: p for p in args.baseline_dir.glob("rib_*.parquet")}
    cand_files = {p.name: p for p in args.candidate_dir.glob("rib_*.parquet")}
    if not base_files or not cand_files:
        raise SystemExit(f"no rib_*.parquet in {args.baseline_dir} or {args.candidate_dir}")

    common = sorted(base_files.keys() & cand_files.keys())
    print(f"{len(common)} common snapshots "
          f"({len(base_files) - len(common)} baseline-only, "
          f"{len(cand_files) - len(common)} candidate-only)")

    problems_by_file: dict[str, list[str]] = {}
    cc_totals: dict[str, int] = {}
    for name in common:
        base = pd.read_parquet(base_files[name])
        cand = pd.read_parquet(cand_files[name])
        problems = compare_snapshot(base, cand)
        if problems:
            problems_by_file[name] = problems
        if "cc" in cand.columns:
            for cc, n in cand["cc"].fillna("IR").value_counts().items():
                cc_totals[cc] = cc_totals.get(cc, 0) + int(n)

    print("candidate rows by cc (all common snapshots):",
          dict(sorted(cc_totals.items())) or "no cc column")

    if problems_by_file:
        print(f"\nMISMATCHES in {len(problems_by_file)} snapshot(s):")
        for name, probs in sorted(problems_by_file.items()):
            for prob in probs:
                print(f"  {name}: {prob}")
        raise SystemExit(1)
    print("\nall common snapshots identical on IR rows")


if __name__ == "__main__":
    main()
