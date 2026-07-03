"""Stage 1 CLI: build the IR ASN/prefix population files.

Usage:
    python -m src.population [--config-dir config] [--force]

Outputs:
    data/population/ir_asns.csv
    data/population/ir_prefixes.csv
    data/population/ir_asn_classification.csv  (merged, never clobbers manual entries)
"""

import argparse
import csv
from pathlib import Path

from src.common.cache import atomic_write, download
from src.common.config import CONFIG_DIR, DATA_DIR, Config
from src.common.log import get_logger
from src.population.as2org import fetch_as2org
from src.population.classification import (
    merge_classification,
    read_classification,
    write_classification,
)
from src.population.delegation import parse_delegations

log = get_logger("population")


def run(config_dir: Path, force: bool = False) -> None:
    cfg = Config.load(config_dir)
    pop_dir = DATA_DIR / "population"
    raw_dir = DATA_DIR / "raw"
    pop_dir.mkdir(parents=True, exist_ok=True)

    delegation_path = download(
        cfg.source("ripe_delegated_extended"),
        raw_dir / "delegated-ripencc-extended-latest",
        force=force,
    )
    with open(delegation_path) as f:
        asn_delegations, prefix_delegations = parse_delegations(f, cc="IR")

    asns = sorted({d.asn for d in asn_delegations})
    prefixes = [(d.prefix, d.family) for d in prefix_delegations]
    log.info("IR population: %d ASNs, %d prefixes", len(asns), len(prefixes))

    def _write_asns(tmp: Path) -> None:
        with open(tmp, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["asn"])
            writer.writerows([a] for a in asns)

    def _write_prefixes(tmp: Path) -> None:
        with open(tmp, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["prefix", "family"])
            writer.writerows(prefixes)

    atomic_write(pop_dir / "ir_asns.csv", _write_asns)
    atomic_write(pop_dir / "ir_prefixes.csv", _write_prefixes)

    org_names = fetch_as2org(cfg.source("caida_as2org_index"), raw_dir)
    classification_path = pop_dir / "ir_asn_classification.csv"
    existing = read_classification(classification_path)
    merged = merge_classification(existing, asns, org_names)
    write_classification(classification_path, merged)
    n_manual = sum(1 for r in merged if r["type"])
    log.info(
        "classification: %d rows (%d manually classified, %d pending) -> %s",
        len(merged), n_manual, len(merged) - n_manual, classification_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    parser.add_argument("--force", action="store_true", help="re-download cached inputs")
    args = parser.parse_args()
    run(args.config_dir, force=args.force)


if __name__ == "__main__":
    main()
