"""Unit tests for the extended-delegation parser and CIDR conversion."""

from src.population.delegation import ipv4_range_to_cidrs, parse_delegations

FIXTURE = """\
2|ripencc|20260101|171331|19830705|20260101|+0100
ripencc|*|ipv4|*|63893|summary
# a comment line
ripencc|IR|asn|12880|1|20030723|allocated|xxx
ripencc|IR|asn|64496|3|20100101|assigned|yyy
ripencc|IR|asn|65550|1|20100101|reserved|zzz
ripencc|DE|asn|3320|1|19930101|allocated|ddd
ripencc|IR|ipv4|2.144.0.0|65536|20100512|allocated|xxx
ripencc|IR|ipv4|5.22.192.0|6144|20120403|allocated|xxx
ripencc|IR|ipv4|91.98.0.0|131072|20070528|available|xxx
ripencc|IR|ipv6|2a01:5e00::|32|20080623|allocated|xxx
ripencc|DE|ipv6|2001:db8::|32|20080101|allocated|ddd
"""


def test_parse_filters_country_and_status():
    asns, prefixes = parse_delegations(FIXTURE.splitlines(), cc="IR")
    asn_numbers = [a.asn for a in asns]
    # reserved AS65550 and German AS3320 excluded; 64496 expands to 3 ASNs
    assert asn_numbers == [12880, 64496, 64497, 64498]
    # 'available' ipv4 row and German ipv6 row excluded
    assert all(p.prefix != "91.98.0.0/15" for p in prefixes)
    families = {p.family for p in prefixes}
    assert families == {4, 6}


def test_asn_count_expansion():
    asns, _ = parse_delegations(
        ["ripencc|IR|asn|100|5|20200101|allocated|id"], cc="IR"
    )
    assert [a.asn for a in asns] == [100, 101, 102, 103, 104]


def test_ipv4_power_of_two_count():
    _, prefixes = parse_delegations(FIXTURE.splitlines(), cc="IR")
    assert any(p.prefix == "2.144.0.0/16" for p in prefixes)


def test_ipv4_non_power_of_two_count_splits():
    # 6144 addresses = 4096 (/20) + 2048 (/21)
    cidrs = list(ipv4_range_to_cidrs("5.22.192.0", 6144))
    assert cidrs == ["5.22.192.0/20", "5.22.208.0/21"]


def test_ipv6_prefix_length():
    _, prefixes = parse_delegations(FIXTURE.splitlines(), cc="IR")
    v6 = [p.prefix for p in prefixes if p.family == 6]
    assert v6 == ["2a01:5e00::/32"]


def test_skips_headers_comments_and_summaries():
    asns, prefixes = parse_delegations(FIXTURE.splitlines()[:3], cc="IR")
    assert asns == [] and prefixes == []
