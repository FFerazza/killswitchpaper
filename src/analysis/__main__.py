"""Stage 5 CLI: build the joined, figure-ready tables under outputs/.

Usage:
    python -m src.analysis [--only visibility_by_type|bgp_vs_ioda|upstream_transitions|event_speed]

Each table is built from whatever stage outputs exist; missing inputs fail
with a message saying which stage to run.
"""

import argparse
from pathlib import Path

import pandas as pd

from src.common.config import CONFIG_DIR, DATA_DIR, OUTPUTS_DIR, Config
from src.common.log import get_logger
from src.analysis import joins

log = get_logger("analysis")

TABLES = ["visibility_by_type", "bgp_vs_ioda", "upstream_transitions", "event_speed"]


def _load_visibility() -> pd.DataFrame:
    path = DATA_DIR / "bgp" / "visibility_timeseries.parquet"
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make bgp-ribs` (or test-week) first")
    return pd.read_parquet(path)


def _load_classification() -> pd.DataFrame:
    path = DATA_DIR / "population" / "ir_asn_classification.csv"
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make population` first")
    return pd.read_csv(path, dtype={"asn": int, "org_name": str, "type": str, "notes": str})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    parser.add_argument("--only", choices=TABLES, help="build a single table")
    args = parser.parse_args()

    cfg = Config.load(args.config_dir)
    tables = [args.only] if args.only else TABLES

    if "visibility_by_type" in tables:
        joins.visibility_by_type(
            _load_visibility(), _load_classification(),
            OUTPUTS_DIR / "visibility_by_type.parquet",
        )
    if "bgp_vs_ioda" in tables:
        # D-013: baselines from the fixed P0 reference window (data/ioda/baseline/),
        # thresholds provisional until the D-013 procedure finalizes them.
        joins.bgp_vs_ioda(
            _load_visibility(),
            DATA_DIR / "ioda" / "asn",
            DATA_DIR / "ioda" / "baseline" / "asn",
            visibility_announced_min=cfg.analysis["visibility_announced_min"],
            probing_dark_ratio=cfg.analysis["probing_dark_ratio"],
            probing_adequacy=cfg.analysis["probing_adequacy"],
            out_path=OUTPUTS_DIR / "bgp_vs_ioda.parquet",
            excluded_out_path=OUTPUTS_DIR / "probing_excluded_asns.csv",
        )
    if "upstream_transitions" in tables:
        joins.upstream_transitions(
            _load_visibility(), OUTPUTS_DIR / "upstream_transitions.parquet"
        )
    if "event_speed" in tables:
        joins.event_speed(DATA_DIR / "bgp" / "events", OUTPUTS_DIR / "event_speed.parquet")


if __name__ == "__main__":
    main()
