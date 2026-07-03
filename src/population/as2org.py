"""CAIDA as2org: locate the latest dataset, parse it, map ASN -> org name."""

import gzip
import json
import re
from pathlib import Path

import requests

from src.common.cache import download
from src.common.log import get_logger

log = get_logger("population.as2org")

_JSONL_RE = re.compile(r'href="((\d{8})\.as-org2info\.jsonl\.gz)"')


def latest_as2org_url(index_url: str) -> str:
    """Scrape the CAIDA index page for the most recent as-org2info jsonl file."""
    resp = requests.get(index_url, timeout=60)
    resp.raise_for_status()
    matches = _JSONL_RE.findall(resp.text)
    if not matches:
        raise RuntimeError(f"No as-org2info.jsonl.gz files found at {index_url}")
    filename, _date = max(matches, key=lambda m: m[1])
    return index_url.rstrip("/") + "/" + filename


def parse_as2org(path: Path) -> dict[int, str]:
    """Parse an as-org2info.jsonl.gz file into {asn: org_name}.

    The file mixes two record types: Organization (organizationId -> name)
    and ASN (asn -> organizationId). Two passes over the org table are not
    needed; org records precede their use, but we resolve at the end anyway
    to be order-independent.
    """
    orgs: dict[str, str] = {}
    asn_to_org_id: dict[int, str] = {}
    asn_own_name: dict[int, str] = {}
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rec_type = rec.get("type")
            if rec_type == "Organization":
                orgs[rec["organizationId"]] = rec.get("name", "")
            elif rec_type == "ASN":
                asn = int(rec["asn"])
                asn_to_org_id[asn] = rec.get("organizationId", "")
                if rec.get("name"):
                    asn_own_name[asn] = rec["name"]
    result: dict[int, str] = {}
    for asn, org_id in asn_to_org_id.items():
        result[asn] = orgs.get(org_id) or asn_own_name.get(asn, "")
    return result


def fetch_as2org(index_url: str, cache_dir: Path) -> dict[int, str]:
    """Download (cached) and parse the latest as2org dataset."""
    url = latest_as2org_url(index_url)
    dest = cache_dir / url.rsplit("/", 1)[-1]
    download(url, dest)
    mapping = parse_as2org(dest)
    log.info("as2org: %d ASN->org mappings", len(mapping))
    return mapping
