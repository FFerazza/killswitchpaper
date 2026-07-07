"""Stage 3 CLI: pull IODA signals (BGP, active probing, darknet).

Usage:
    python -m src.ioda [--start ISO --end ISO | --window NAME] [--country-only]

Pulls country/IR for the window plus every ASN in the Stage 1 population and
the D-014 frozen control population (config/controls.yaml) - the control-side
IODA data D-014's artifact check and any full-period control comparison
depend on. Resumable: per-entity parquets already on disk are skipped.
"""

import argparse
import csv
from pathlib import Path

import yaml

from src.common.config import CONFIG_DIR, DATA_DIR, Config
from src.common.log import get_logger
from src.common.timeutil import to_iso, to_unix
from src.ioda.client import fetch_to_parquet

log = get_logger("ioda")


def load_ir_asns() -> list[int]:
    path = DATA_DIR / "population" / "ir_asns.csv"
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make population` first")
    with open(path, newline="") as f:
        return [int(row["asn"]) for row in csv.DictReader(f)]


def load_control_asns() -> list[int]:
    """D-014 frozen control ASNs (TR/AE/PK) - empty list if not yet frozen."""
    path = CONFIG_DIR / "controls.yaml"
    if not path.exists():
        return []
    with open(path) as f:
        controls = yaml.safe_load(f)
    return [asn for asns in controls["asns"].values() for asn in asns]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    parser.add_argument("--start", help="ISO 8601 start (default: study period)")
    parser.add_argument("--end", help="ISO 8601 end (default: study period)")
    parser.add_argument("--window", help="named window from phases.yaml (e.g. test_week)")
    parser.add_argument("--country-only", action="store_true",
                        help="only pull country/IR, skip per-ASN signals")
    parser.add_argument("--baseline", action="store_true",
                        help="D-013: pull the probing-baseline reference window "
                             "into data/ioda/baseline/ instead of data/ioda/")
    args = parser.parse_args()

    cfg = Config.load(args.config_dir)
    if args.baseline and (args.window or args.start or args.end):
        parser.error("--baseline uses the configured probing_baseline_window; "
                     "it is mutually exclusive with --window/--start/--end")
    if args.window and (args.start or args.end):
        parser.error("--window and --start/--end are mutually exclusive")
    if args.baseline:
        w = cfg.probing_baseline_window
        start, end = w.start, w.end
    elif args.window:
        w = cfg.window_by_name(args.window)
        start, end = w.start, w.end
    else:
        start = to_unix(args.start) if args.start else cfg.study_period.start
        end = to_unix(args.end) if args.end else cfg.study_period.end

    base = cfg.source("ioda_api_base")
    signals = cfg.ioda_signals
    interval = cfg.ioda_request_interval
    ioda_dir = DATA_DIR / "ioda" / "baseline" if args.baseline else DATA_DIR / "ioda"
    log.info("window %s -> %s, signals %s -> %s", to_iso(start), to_iso(end), signals, ioda_dir)

    max_query = cfg.ioda_max_query_seconds
    fetch_to_parquet(
        ioda_dir / "country_IR.parquet", base, "country", "IR",
        start, end, signals, interval, max_query,
    )

    if not args.country_only:
        asns = load_ir_asns() + load_control_asns()
        log.info("pulling %d ASNs", len(asns))
        for i, asn in enumerate(asns, 1):
            fetch_to_parquet(
                ioda_dir / "asn" / f"{asn}.parquet", base, "asn", str(asn),
                start, end, signals, interval, max_query,
            )
            if i % 50 == 0:
                log.info("progress: %d/%d ASNs", i, len(asns))


if __name__ == "__main__":
    main()
