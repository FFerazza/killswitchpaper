"""D-002 snapshot validity: per-collector full-feed accounting and the integrity guard."""

import pytest

from src.bgp.ribs import (
    CollectorIntegrityError,
    check_collector_integrity,
    per_collector_fullfeed,
)


def peer(collector: str, asn: int) -> tuple:
    return (collector, asn, f"192.0.2.{asn}")


class TestPerCollectorFullfeed:
    def test_counts_by_collector_and_family(self):
        full_feed = {
            "ipv4": {peer("route-views2", 1), peer("route-views2", 2), peer("linx", 3)},
            "ipv6": {peer("linx", 3)},
        }
        counts = per_collector_fullfeed(full_feed)
        assert counts == {
            "route-views2": {"ipv4": 2, "ipv6": 0},
            "linx": {"ipv4": 1, "ipv6": 1},
        }

    def test_empty_stream_yields_no_counts(self):
        assert per_collector_fullfeed({"ipv4": set(), "ipv6": set()}) == {}


class TestCheckCollectorIntegrity:
    def test_passes_when_every_collector_contributes(self):
        counts = {
            "route-views2": {"ipv4": 21, "ipv6": 15},
            "route-views.linx": {"ipv4": 97, "ipv6": 14},
        }
        check_collector_integrity(counts, ["route-views2", "route-views.linx"])

    def test_single_family_contribution_suffices(self):
        counts = {"route-views2": {"ipv4": 0, "ipv6": 1}}
        check_collector_integrity(counts, ["route-views2"])

    def test_raises_when_collector_absent(self):
        counts = {"route-views2": {"ipv4": 21, "ipv6": 15}}
        with pytest.raises(CollectorIntegrityError, match="route-views.linx"):
            check_collector_integrity(counts, ["route-views2", "route-views.linx"])

    def test_raises_when_collector_present_but_no_fullfeed_peers(self):
        counts = {
            "route-views2": {"ipv4": 21, "ipv6": 15},
            "rrc12": {"ipv4": 0, "ipv6": 0},
        }
        with pytest.raises(CollectorIntegrityError, match="rrc12"):
            check_collector_integrity(counts, ["route-views2", "rrc12"])

    def test_extra_unconfigured_collectors_are_ignored(self):
        counts = {
            "route-views2": {"ipv4": 21, "ipv6": 15},
            "stray": {"ipv4": 5, "ipv6": 0},
        }
        check_collector_integrity(counts, ["route-views2"])
