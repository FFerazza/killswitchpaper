"""Data-completeness inventory: expected artifacts (from config) vs disk.

For every data series the pipeline produces, derive the EXPECTED file set
from config (snapshot grids, backfill ranges, event windows, population and
control lists) and diff it against what is on disk. Answers "do we have all
the data?" with one command instead of eyeballed directory listings.

Series:
  ribs_test_week    primary RIB snapshots over the test week
  ribs_study_period primary RIB snapshots over the full study period
  ribs_ris          D-012 secondary series over all backfill ranges (D-015 incl.)
  events            one parquet per configured event window
  ioda_asn          per-ASN IODA pulls: IR population + frozen controls
  ioda_baseline     D-013 baseline pulls: IR population + frozen controls
  population        Stage 1 outputs and frozen control config

Consolidated timeseries parquets are checked for staleness: their snapshot
set must equal the snapshot files on disk, otherwise they predate the latest
fills and must be rebuilt.

Unexpected files (present but not derivable from config) are reported but
never deleted and never fail a check — see the concurrent-jobs incident log
and the D-014 selection by-products before cleaning anything up.

Exit status: 0 unless a series named via --require is incomplete or stale.

Usage: python -m src.analysis.inventory --require ribs_ris events ioda_baseline
"""

import argparse
from pathlib import Path

from src.common.config import Config
from src.common.timeutil import snapshot_times, to_iso

DATA_DIR = Path("data")


def _grid(window, interval_hours: int) -> set[int]:
    return set(snapshot_times(window.start, window.end, interval_hours))


def _rib_dir_ts(d: Path) -> set[int]:
    return {int(p.stem.split("_")[1]) for p in d.glob("rib_*.parquet")}


def _consolidated_ts(path: Path) -> "set[int] | None":
    if not path.exists():
        return None
    import pyarrow.parquet as pq

    return set(pq.read_table(path, columns=["ts"]).column("ts").unique().to_pylist())


def _asn_files(d: Path) -> set[str]:
    return {p.stem for p in d.glob("*.parquet")}


def _expected_asns() -> tuple[set[str], set[str]]:
    """(IR ASNs, frozen control ASNs) from Stage 1 output + D-014 freeze."""
    import csv

    import yaml

    with open(DATA_DIR / "population" / "ir_asns.csv") as f:
        ir = {row["asn"] for row in csv.DictReader(f)}
    with open(Path("config") / "controls.yaml") as f:
        ctl = yaml.safe_load(f)
    controls = {str(a) for country in ctl["asns"].values() for a in country}
    return ir, controls


def check_rib_series(name: str, ribs_dir: Path, expected_ts: set[int],
                     consolidated: Path) -> dict:
    present = _rib_dir_ts(ribs_dir) if ribs_dir.exists() else set()
    missing = expected_ts - present
    result = {
        "name": name,
        "expected": len(expected_ts),
        "present": len(expected_ts & present),
        "missing": sorted(missing),
        "notes": [],
    }
    extra = present - expected_ts
    if extra:
        result["notes"].append(f"{len(extra)} snapshot(s) outside this grid (other series/window)")
    cons = _consolidated_ts(consolidated)
    if cons is None:
        result["notes"].append(f"no consolidated file {consolidated.name}")
        result["stale"] = True
    else:
        # The consolidated file must reflect exactly the snapshots on disk.
        result["stale"] = cons != present
        if result["stale"]:
            result["notes"].append(
                f"{consolidated.name} is STALE: covers {len(cons)} ts, disk has "
                f"{len(present)} - rebuild via consolidation"
            )
    return result


def check_file_set(name: str, directory: Path, expected: set[str],
                   suffix: str = ".parquet") -> dict:
    present = {p.stem for p in directory.glob(f"*{suffix}")} if directory.exists() else set()
    missing = sorted(expected - present)
    extra = sorted(present - expected)
    notes = []
    if extra:
        notes.append(f"{len(extra)} unexpected file(s) (kept; see docstring): "
                     f"{extra[:5]}{'...' if len(extra) > 5 else ''}")
    return {"name": name, "expected": len(expected), "present": len(expected & present),
            "missing": missing, "notes": notes}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require", nargs="*", default=[],
                    help="series that must be complete; exit 1 otherwise")
    args = ap.parse_args()

    cfg = Config.load()
    interval = cfg.rib_interval_hours
    ir_asns, control_asns = _expected_asns()

    ris_expected: set[int] = set()
    for window in cfg.ris_backfill_ranges:
        ris_expected |= _grid(window, interval)

    results = [
        check_rib_series("ribs_test_week", DATA_DIR / "bgp" / "ribs",
                         _grid(cfg.test_week, interval),
                         DATA_DIR / "bgp" / "visibility_timeseries.parquet"),
        check_rib_series("ribs_study_period", DATA_DIR / "bgp" / "ribs",
                         _grid(cfg.study_period, interval),
                         DATA_DIR / "bgp" / "visibility_timeseries.parquet"),
        check_rib_series("ribs_ris", DATA_DIR / "bgp" / "ribs_ris", ris_expected,
                         DATA_DIR / "bgp" / "visibility_timeseries_ris.parquet"),
        check_file_set("events", DATA_DIR / "bgp" / "events",
                       {w.name for w in cfg.event_windows}),
        check_file_set("ioda_asn", DATA_DIR / "ioda" / "asn", ir_asns | control_asns),
        check_file_set("ioda_baseline", DATA_DIR / "ioda" / "baseline" / "asn",
                       ir_asns | control_asns),
        check_file_set("population", DATA_DIR / "population",
                       {"ir_asns", "ir_prefixes", "ir_asn_classification",
                        "control_prefixes"}, suffix=".csv"),
    ]

    unknown = set(args.require) - {r["name"] for r in results}
    if unknown:
        raise SystemExit(f"unknown series in --require: {sorted(unknown)}")

    failures = []
    for r in results:
        complete = not r["missing"] and not r.get("stale", False)
        status = "OK" if complete else "INCOMPLETE"
        required = r["name"] in args.require
        print(f"[{status}] {r['name']}: {r['present']}/{r['expected']}"
              + (" (required)" if required else ""))
        for ts in r["missing"][:10]:
            label = to_iso(ts) if isinstance(ts, int) else ts
            print(f"    missing: {label}")
        if len(r["missing"]) > 10:
            print(f"    ... and {len(r['missing']) - 10} more")
        for note in r["notes"]:
            print(f"    note: {note}")
        if required and not complete:
            failures.append(r["name"])

    if failures:
        raise SystemExit(f"required series incomplete: {failures}")


if __name__ == "__main__":
    main()
