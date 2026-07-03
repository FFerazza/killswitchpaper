"""D-012 RIS direct fetch: URL construction and collector tagging."""

import pytest

from src.bgp.risfiles import CollectorElem, bview_url

BASE = "https://data.ris.ripe.net"


class TestBviewUrl:
    def test_midnight_snapshot(self):
        # 2026-02-28 00:00:00 UTC
        assert bview_url(BASE, "rrc00", 1772236800) == (
            "https://data.ris.ripe.net/rrc00/2026.02/bview.20260228.0000.gz"
        )

    def test_0800_snapshot_and_month_rollover(self):
        # 2026-03-02 08:00:00 UTC -> month directory 2026.03
        assert bview_url(BASE, "rrc12", 1772438400) == (
            "https://data.ris.ripe.net/rrc12/2026.03/bview.20260302.0800.gz"
        )

    def test_off_grid_timestamp_rejected(self):
        with pytest.raises(ValueError, match="bview grid"):
            bview_url(BASE, "rrc00", 1772236800 + 3600)  # 01:00 UTC


class FakeElem:
    collector = "singlefile"
    peer_asn = 64500
    fields = {"prefix": "192.0.2.0/24"}


class TestCollectorElem:
    def test_overrides_collector_and_delegates_the_rest(self):
        wrapped = CollectorElem(FakeElem(), "rrc00")
        assert wrapped.collector == "rrc00"
        assert wrapped.peer_asn == 64500
        assert wrapped.fields["prefix"] == "192.0.2.0/24"

    def test_missing_attribute_still_raises(self):
        with pytest.raises(AttributeError):
            CollectorElem(FakeElem(), "rrc00").nonexistent
