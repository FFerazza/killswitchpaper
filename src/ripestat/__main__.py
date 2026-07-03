"""Stage 4 CLI: RIPEstat routing-history cross-check.

Usage:
    python -m src.ripestat fetch                 # pull routing history for sample ASNs
    python -m src.ripestat compare               # flag disagreements vs Stage 2 output

Sample ASNs come from `ripestat_sample_asns` in config/phases.yaml.
"""

import argparse
import json
from pathlib import Path

from src.common.cache import atomic_write, get_json
from src.common.config import CONFIG_DIR, DATA_DIR, OUTPUTS_DIR, Config
from src.common.log import get_logger
from src.ripestat.compare import run_comparison

log = get_logger("ripestat")


def fetch(cfg: Config, ripestat_dir: Path, force: bool = False) -> None:
    url = cfg.source("ripestat_routing_history")
    for asn in cfg.ripestat_sample_asns:
        dest = ripestat_dir / f"{asn}.json"
        if dest.exists() and not force:
            log.info("skip existing %s", dest)
            continue
        doc = get_json(url, params={"resource": f"AS{asn}"})

        def _write(tmp: Path, doc: dict = doc) -> None:
            with open(tmp, "w") as f:
                json.dump(doc, f)

        atomic_write(dest, _write)
        log.info("AS%d routing history -> %s", asn, dest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    p_fetch = sub.add_parser("fetch", help="download routing history for sample ASNs")
    p_fetch.add_argument("--force", action="store_true", help="re-download cached responses")
    sub.add_parser("compare", help="compare against pipeline visibility series")
    args = parser.parse_args()

    cfg = Config.load(args.config_dir)
    ripestat_dir = DATA_DIR / "ripestat"

    if args.command == "fetch":
        fetch(cfg, ripestat_dir, force=args.force)
    else:
        result = run_comparison(
            cfg.ripestat_sample_asns,
            ripestat_dir,
            DATA_DIR / "bgp" / "visibility_timeseries.parquet",
            cfg.analysis["visibility_announced_min"],
        )
        out = OUTPUTS_DIR / "ripestat_comparison.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(out, index=False)
        n_bad = int((~result["agree"]).sum())
        log.info("comparison: %d rows, %d disagreements -> %s", len(result), n_bad, out)


if __name__ == "__main__":
    main()
