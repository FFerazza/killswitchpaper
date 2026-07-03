"""Merge logic for the hand-curated ASN classification file.

data/population/ir_asn_classification.csv is a research artifact: `type` and
`notes` are filled in by hand. The code must NEVER overwrite manual entries —
it only adds newly seen ASNs (type left blank) and fills in missing org names.
"""

import csv
from pathlib import Path

from src.common.cache import atomic_write

FIELDNAMES = ["asn", "org_name", "type", "notes"]

VALID_TYPES = {
    "state_telecom", "mobile", "isp", "government",
    "financial", "hosting", "education", "other", "",
}


def read_classification(path: Path) -> dict[int, dict[str, str]]:
    """Read the existing classification CSV into {asn: row}. Missing file -> {}."""
    if not path.exists():
        return {}
    rows: dict[int, dict[str, str]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows[int(row["asn"])] = {k: (row.get(k) or "").strip() for k in FIELDNAMES}
    return rows


def merge_classification(
    existing: dict[int, dict[str, str]],
    asns: list[int],
    org_names: dict[int, str],
) -> list[dict[str, str]]:
    """Merge the current ASN population into the existing classification.

    - Existing rows are kept verbatim (manual `type`/`notes` are sacred);
      only a blank org_name is filled from as2org.
    - New ASNs are added with org_name pre-filled and `type` blank.
    - Rows for ASNs no longer in the population are kept (never drop manual work).
    """
    merged = {asn: dict(row) for asn, row in existing.items()}
    for asn in asns:
        if asn in merged:
            if not merged[asn]["org_name"]:
                merged[asn]["org_name"] = org_names.get(asn, "")
        else:
            merged[asn] = {
                "asn": str(asn),
                "org_name": org_names.get(asn, ""),
                "type": "",
                "notes": "",
            }
    for asn, row in merged.items():
        row["asn"] = str(asn)
    return [merged[asn] for asn in sorted(merged)]


def write_classification(path: Path, rows: list[dict[str, str]]) -> None:
    """Atomically write the classification CSV."""

    def _write(tmp: Path) -> None:
        with open(tmp, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

    atomic_write(path, _write)
