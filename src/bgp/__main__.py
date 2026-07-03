"""Stage 2 CLI: BGP visibility from RIS + RouteViews.

Usage:
    python -m src.bgp ribs   [--start ISO --end ISO | --window NAME]
    python -m src.bgp events [--window NAME ...]      # default: all event windows

Requires Stage 1 outputs (data/population/ir_prefixes.csv) and pybgpstream.
Both subcommands are resumable: existing per-snapshot / per-window parquets
are skipped.
"""

import argparse
import csv
from pathlib import Path

from src.common.config import CONFIG_DIR, DATA_DIR, Config, Window
from src.common.log import get_logger
from src.common.timeutil import to_unix
from src.bgp.events import run_events
from src.bgp.ribs import consolidate, run_ribs

log = get_logger("bgp")


def load_ir_prefixes() -> list[str]:
    path = DATA_DIR / "population" / "ir_prefixes.csv"
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make population` first")
    with open(path, newline="") as f:
        return [row["prefix"] for row in csv.DictReader(f)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ribs = sub.add_parser("ribs", help="RIB snapshots -> visibility timeseries")
    p_ribs.add_argument("--start", help="ISO 8601 start (default: study period)")
    p_ribs.add_argument("--end", help="ISO 8601 end (default: study period)")
    p_ribs.add_argument("--window", help="named window from phases.yaml (e.g. test_week)")

    p_events = sub.add_parser("events", help="update streams in boundary windows")
    p_events.add_argument(
        "--window", action="append", dest="windows",
        help="window name from phases.yaml; repeatable (default: all event windows)",
    )

    p_ris = sub.add_parser(
        "ribs-ris",
        help="D-012 secondary series: RouteViews via broker + RIS via direct bview fetch",
    )
    p_ris.add_argument(
        "--keep-files", action="store_true",
        help="keep downloaded bview files instead of deleting after each snapshot",
    )

    args = parser.parse_args()
    cfg = Config.load(args.config_dir)
    prefixes = load_ir_prefixes()
    log.info("loaded %d IR prefixes", len(prefixes))

    if args.command == "ribs":
        if args.window and (args.start or args.end):
            parser.error("--window and --start/--end are mutually exclusive")
        if args.window:
            w = cfg.window_by_name(args.window)
            start, end = w.start, w.end
        else:
            start = to_unix(args.start) if args.start else cfg.study_period.start
            end = to_unix(args.end) if args.end else cfg.study_period.end
        ribs_dir = DATA_DIR / "bgp" / "ribs"
        run_ribs(cfg, ribs_dir, prefixes, start, end)
        consolidate(ribs_dir, DATA_DIR / "bgp" / "visibility_timeseries.parquet")
    elif args.command == "ribs-ris":
        from src.bgp.backfill import run_ribs_ris

        ribs_ris_dir = DATA_DIR / "bgp" / "ribs_ris"
        run_ribs_ris(
            cfg, ribs_ris_dir, DATA_DIR / "raw" / "ris", prefixes,
            keep_files=args.keep_files,
        )
        consolidate(ribs_ris_dir, DATA_DIR / "bgp" / "visibility_timeseries_ris.parquet")
    else:
        windows: list[Window]
        if args.windows:
            windows = [cfg.window_by_name(name) for name in args.windows]
        else:
            windows = cfg.event_windows
        run_events(cfg, DATA_DIR / "bgp" / "events", prefixes, windows)


if __name__ == "__main__":
    main()
