"""Parser for RIR extended delegation files (RFC-less but well-known format).

Line format (pipe-separated):
    registry|cc|type|start|value|date|status|opaque-id[|extensions...]

For `asn` rows, value = count of consecutive ASNs starting at `start`.
For `ipv4` rows, value = count of addresses starting at `start` (NOT a prefix
length; counts are not always powers of two, so a row may expand to several
CIDR prefixes).
For `ipv6` rows, value = prefix length.
"""

import ipaddress
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

_VALID_STATUSES = {"allocated", "assigned"}


@dataclass(frozen=True)
class AsnDelegation:
    asn: int
    status: str
    date: str


@dataclass(frozen=True)
class PrefixDelegation:
    prefix: str
    family: int  # 4 or 6
    status: str
    date: str


def parse_delegations(
    lines: Iterable[str], cc: str = "IR"
) -> tuple[list[AsnDelegation], list[PrefixDelegation]]:
    """Parse an extended delegation file, keeping rows for country `cc`.

    Returns (asns, prefixes). Comment lines, the version header, and summary
    lines are skipped. Only `allocated`/`assigned` rows are kept.
    """
    asns: list[AsnDelegation] = []
    prefixes: list[PrefixDelegation] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("|")
        if len(fields) < 7 or fields[1] != cc:
            continue
        _, _, rtype, start, value, date, status = fields[:7]
        if status not in _VALID_STATUSES:
            continue
        if rtype == "asn":
            first = int(start)
            for asn in range(first, first + int(value)):
                asns.append(AsnDelegation(asn=asn, status=status, date=date))
        elif rtype == "ipv4":
            for cidr in ipv4_range_to_cidrs(start, int(value)):
                prefixes.append(PrefixDelegation(prefix=cidr, family=4, status=status, date=date))
        elif rtype == "ipv6":
            prefix = f"{start}/{int(value)}"
            prefixes.append(PrefixDelegation(prefix=prefix, family=6, status=status, date=date))
    return asns, prefixes


def ipv4_range_to_cidrs(start: str, count: int) -> Iterator[str]:
    """Convert an IPv4 start address + address count to minimal CIDR prefixes."""
    first = ipaddress.IPv4Address(start)
    last = first + (count - 1)
    for net in ipaddress.summarize_address_range(first, last):
        yield str(net)
