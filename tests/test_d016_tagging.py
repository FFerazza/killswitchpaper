"""D-016: control-prefix derivation and cc tagging through Stage 2 outputs."""

import pandas as pd
import pytest

from src.bgp.ribs import consolidate, process_snapshot
from src.common.prefixmatch import PrefixMatcher
from src.population.controls import control_org_prefixes

DELEGATION_LINES = [
    "2|ripencc|1751500800|123456|19830705|20260703|+0000",  # version header
    "ripencc|*|ipv4|*|45671|summary",
    "ripencc|TR|ipv4|78.160.0.0|2097152|20100101|allocated|org-turk",
    "ripencc|TR|ipv6|2a02:e0::|29|20100101|allocated|org-turk",
    "ripencc|TR|asn|9121|1|20100101|allocated|org-turk",
    # Same country, org holds no frozen ASN -> excluded
    "ripencc|TR|ipv4|193.0.0.0|256|20100101|allocated|org-other",
    "ripencc|TR|asn|64512|1|20100101|allocated|org-other",
    # Frozen ASN's org also has a reserved block -> excluded by status
    "ripencc|TR|ipv4|10.0.0.0|256|20100101|reserved|org-turk",
    # Other country ignored regardless of org
    "ripencc|AE|ipv4|94.200.0.0|65536|20100101|allocated|org-turk",
]


class TestControlOrgPrefixes:
    def test_blocks_of_frozen_asn_orgs_only(self):
        rows = control_org_prefixes(DELEGATION_LINES, "TR", {9121})
        assert rows == [
            ("78.160.0.0/11", 4, "9121"),
            ("2a02:e0::/29", 6, "9121"),
        ]

    def test_no_frozen_asns_yields_nothing(self):
        assert control_org_prefixes(DELEGATION_LINES, "TR", {65000}) == []


class Elem:
    """Minimal stand-in for a pybgpstream RIB element."""

    def __init__(self, prefix: str, path: str = "64500 64501",
                 collector: str = "c1", peer_asn: int = 1):
        self.collector = collector
        self.peer_asn = peer_asn
        self.peer_address = f"192.0.2.{peer_asn}"
        self.fields = {"prefix": prefix, "as-path": path}


class TestSnapshotTagging:
    def test_cc_column_tags_populations(self, tmp_path):
        matcher = PrefixMatcher({"IR": ["5.22.192.0/18"], "TR": ["78.160.0.0/11"]})
        elems = [
            Elem("5.22.200.0/24"),
            Elem("78.170.1.0/24"),
            Elem("8.8.8.0/24"),  # unmatched filler so the peer is full-feed
        ]
        out = tmp_path / "rib_100.parquet"
        process_snapshot(100, ["c1"], matcher, {"ipv4": 3, "ipv6": 1}, out, elems=elems)
        df = pd.read_parquet(out)
        assert dict(zip(df["prefix"], df["cc"])) == {
            "5.22.200.0/24": "IR",
            "78.170.1.0/24": "TR",
        }


class TestConsolidateBackfillsCc:
    def test_pre_d016_snapshots_read_as_ir(self, tmp_path):
        old = pd.DataFrame({"ts": [100], "prefix": ["5.22.200.0/24"], "visibility": [1.0]})
        new = pd.DataFrame({"ts": [200], "prefix": ["78.170.1.0/24"],
                            "visibility": [1.0], "cc": ["TR"]})
        old.to_parquet(tmp_path / "rib_100.parquet", index=False)
        new.to_parquet(tmp_path / "rib_200.parquet", index=False)
        out = tmp_path / "series.parquet"
        consolidate(tmp_path, out)
        df = pd.read_parquet(out).set_index("ts")
        assert df.loc[100, "cc"] == "IR"
        assert df.loc[200, "cc"] == "TR"
