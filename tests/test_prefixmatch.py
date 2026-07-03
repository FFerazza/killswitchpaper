"""Unit tests for radix-tree matching of observed prefixes against IR blocks."""

from src.common.prefixmatch import PrefixMatcher

IR_BLOCKS = ["5.22.192.0/18", "91.98.0.0/15", "2a01:5e00::/32"]


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
