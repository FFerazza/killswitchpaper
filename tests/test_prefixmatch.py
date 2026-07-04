"""Unit tests for radix-tree matching of observed prefixes against IR blocks."""

import pytest

from src.common.prefixmatch import PopulationOverlapError, PrefixMatcher

IR_BLOCKS = ["5.22.192.0/18", "91.98.0.0/15", "2a01:5e00::/32"]
TR_BLOCKS = ["78.160.0.0/11"]


def test_exact_match():
    m = PrefixMatcher(IR_BLOCKS)
    assert m.match("5.22.192.0/18") == "5.22.192.0/18"


def test_more_specific_matches_covering_block():
    m = PrefixMatcher(IR_BLOCKS)
    assert m.match("5.22.200.0/24") == "5.22.192.0/18"
    assert m.match("91.99.32.0/19") == "91.98.0.0/15"


def test_ipv6_more_specific():
    m = PrefixMatcher(IR_BLOCKS)
    assert m.match("2a01:5e00:1234::/48") == "2a01:5e00::/32"


def test_unrelated_prefix_no_match():
    m = PrefixMatcher(IR_BLOCKS)
    assert m.match("8.8.8.0/24") is None
    assert m.match("2001:db8::/32") is None


def test_less_specific_does_not_match():
    # A covering supernet of an IR block is NOT an IR announcement.
    m = PrefixMatcher(IR_BLOCKS)
    assert m.match("5.0.0.0/8") is None


def test_malformed_prefix_returns_none():
    m = PrefixMatcher(IR_BLOCKS)
    assert m.match("not-a-prefix") is None


class TestPopulationTags:
    """D-016: multi-population matcher with country tags."""

    def test_plain_iterable_defaults_to_ir(self):
        m = PrefixMatcher(IR_BLOCKS)
        assert m.match_cc("5.22.200.0/24") == ("5.22.192.0/18", "IR")

    def test_tagged_populations(self):
        m = PrefixMatcher({"IR": IR_BLOCKS, "TR": TR_BLOCKS})
        assert m.match_cc("5.22.200.0/24") == ("5.22.192.0/18", "IR")
        assert m.match_cc("78.170.1.0/24") == ("78.160.0.0/11", "TR")
        assert m.match_cc("8.8.8.0/24") is None
        # match() keeps its pre-D-016 behavior
        assert m.match("78.170.1.0/24") == "78.160.0.0/11"

    def test_overlap_aborts_when_covering_block_added_first(self):
        with pytest.raises(PopulationOverlapError, match="disjoint"):
            PrefixMatcher({"IR": ["5.22.192.0/18"], "TR": ["5.22.200.0/24"]})

    def test_overlap_aborts_when_covered_block_added_first(self):
        with pytest.raises(PopulationOverlapError, match="disjoint"):
            PrefixMatcher({"TR": ["5.22.200.0/24"], "IR": ["5.22.192.0/18"]})

    def test_duplicate_prefix_across_populations_aborts(self):
        with pytest.raises(PopulationOverlapError, match="disjoint"):
            PrefixMatcher({"IR": ["5.22.192.0/18"], "TR": ["5.22.192.0/18"]})

    def test_duplicate_within_population_is_fine(self):
        m = PrefixMatcher({"IR": ["5.22.192.0/18", "5.22.192.0/18"]})
        assert m.match_cc("5.22.192.0/18") == ("5.22.192.0/18", "IR")
