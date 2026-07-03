"""D-014: build and freeze the control population (resolves D-008).

Selection is mechanical, per the decision entry:
  1. Per control country, rank organizations (delegation opaque-id) by total
     delegated IPv4 address space; candidate ASNs are the orgs' ASNs in rank
     order, top N_CANDIDATES per country.
  2. Pull IODA baselines (the D-013 reference month) for all candidates.
  3. Apply the identical D-013 adequacy rule; freeze the first 10 adequate
     ASNs per country into config/controls.yaml.

The frozen file is written once and never regenerated (like the IR
classification CSV): rerunning against an existing controls.yaml aborts.

Usage:
    python -m src.population.controls
"""

import time
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import yaml

from src.common.cache import download
from src.common.config import CONFIG_DIR, DATA_DIR, Config
from src.common.log import get_logger
from src.common.timeutil import to_iso

log = get_logger("population.controls")

COUNTRIES = {"TR": "ripe", "AE": "ripe", "PK": "apnic"}
# Candidate pool depth: D-014's rule is "the 10 largest that PASS adequacy", so the
# pool must be deep enough to find 10 passers; widen further if a country still
# falls short (log warning documents any shortfall).
N_CANDIDATES = 40
N_FROZEN = 10
_VALID_STATUSES = {"allocated", "assigned"}


def org_ranked_asns(lines: Iterable[str], cc: str) -> list[tuple[int, int]]:
    """Return [(asn, org_ipv4_space), ...] for country `cc`, orgs ranked by
    total delegated IPv4 space (descending), ASNs in numeric order within org.

    Uses the extended-format opaque-id to attribute address space to the same
    organization that holds the ASN.
    """
    org_space: dict[str, int] = defaultdict(int)
    org_asns: dict[str, list[int]] = defaultdict(list)
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("|")
        if len(fields) < 8 or fields[1] != cc or fields[6] not in _VALID_STATUSES:
            continue
        rtype, start, value, opaque = fields[2], fields[3], fields[4], fields[7]
        if rtype == "ipv4":
            org_space[opaque] += int(value)
        elif rtype == "asn":
            first = int(start)
            org_asns[opaque].extend(range(first, first + int(value)))
    ranked = []
    for opaque in sorted(org_asns, key=lambda o: org_space.get(o, 0), reverse=True):
        for asn in sorted(org_asns[opaque]):
            ranked.append((asn, org_space.get(opaque, 0)))
    return ranked


def build_candidates(cfg: Config, raw_dir: Path) -> dict[str, list[int]]:
    """Top-N_CANDIDATES ASNs per control country from the RIR delegation files."""
    files = {
        "ripe": download(cfg.source("ripe_delegated_extended"),
                         raw_dir / "delegated-ripencc-extended-latest"),
        "apnic": download(cfg.source("apnic_delegated_extended"),
                          raw_dir / "delegated-apnic-extended-latest"),
    }
    candidates: dict[str, list[int]] = {}
    for cc, registry in COUNTRIES.items():
        with open(files[registry]) as f:
            ranked = org_ranked_asns(f, cc)
        candidates[cc] = [asn for asn, _ in ranked[:N_CANDIDATES]]
        log.info("%s: %d candidate ASNs (largest org space %d addrs)",
                 cc, len(candidates[cc]), ranked[0][1] if ranked else 0)
    return candidates


def freeze_controls(cfg: Config, out_path: Path) -> None:
    """Run the full D-014 selection and freeze config/controls.yaml (write-once)."""
    if out_path.exists():
        raise SystemExit(
            f"{out_path} already exists - the control population is frozen (D-014). "
            "Superseding it requires a new DECISIONS.md entry, not a rerun."
        )
    from src.ioda.client import fetch_to_parquet
    from src.analysis.joins import _probing_baseline

    candidates = build_candidates(cfg, DATA_DIR / "raw")
    w = cfg.probing_baseline_window
    baseline_dir = DATA_DIR / "ioda" / "baseline" / "asn"
    adequacy = cfg.analysis["probing_adequacy"]
    base_url = cfg.source("ioda_api_base")

    frozen: dict[str, list[int]] = {}
    for cc, asns in candidates.items():
        kept: list[int] = []
        for asn in asns:
            fetch_to_parquet(
                baseline_dir / f"{asn}.parquet", base_url, "asn", str(asn),
                w.start, w.end, cfg.ioda_signals, cfg.ioda_request_interval,
            )
            _, adequate, stats = _probing_baseline(
                baseline_dir, asn,
                adequacy["min_nonzero_share"], adequacy["min_median"],
            )
            log.info("%s AS%d: adequate=%s (share=%s median=%s)",
                     cc, asn, adequate, stats["nonzero_share"], stats["median"])
            if adequate:
                kept.append(asn)
            if len(kept) == N_FROZEN:
                break
        if len(kept) < N_FROZEN:
            log.warning("%s: only %d/%d adequate control ASNs among %d candidates",
                        cc, len(kept), N_FROZEN, len(asns))
        frozen[cc] = kept

    doc = {
        "frozen_at": to_iso(int(time.time())),
        "decision": "D-014",
        "countries": list(COUNTRIES),
        "artifact_bin_share": 0.10,
        "asns": frozen,
        "caveats": [],
    }
    with open(out_path, "w") as f:
        f.write("# D-014 frozen control population. Write-once: superseding requires\n"
                "# a new DECISIONS.md entry. Append documented regional events to caveats.\n")
        yaml.safe_dump(doc, f, sort_keys=False)
    log.info("frozen %s control ASNs -> %s",
             {cc: len(a) for cc, a in frozen.items()}, out_path)


def main() -> None:
    cfg = Config.load()
    freeze_controls(cfg, CONFIG_DIR / "controls.yaml")


if __name__ == "__main__":
    main()
