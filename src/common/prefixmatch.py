"""Radix-tree matching of observed BGP prefixes against study populations.

An observed prefix matches if it equals, or is a more-specific of, a
delegated block (e.g. observed 5.22.192.0/21 inside delegated 5.22.192.0/17).

D-016: the tree can hold several populations (IR plus the control countries),
each tagged with its country code. IR and control delegations are disjoint
address space, so a prefix covered by two populations indicates a data error
and construction aborts (fail loudly, never guess).
"""

from collections.abc import Iterable, Mapping

import radix


class PopulationOverlapError(RuntimeError):
    """A prefix is covered by two differently-tagged populations (D-016 rule 3)."""


class PrefixMatcher:
    """Wraps a radix tree of population prefixes; supports IPv4 and IPv6.

    Accepts either a plain iterable of prefixes (a single population, tagged
    "IR" — the pre-D-016 call form) or a mapping of country code -> prefixes.
    """

    def __init__(self, populations: Iterable[str] | Mapping[str, Iterable[str]]):
        if not isinstance(populations, Mapping):
            populations = {"IR": populations}
        self._tree = radix.Radix()
        for cc, prefixes in populations.items():
            for p in prefixes:
                self._add(p, cc)

    def _add(self, prefix: str, cc: str) -> None:
        covering = self._tree.search_best(prefix)
        if covering and covering.data["cc"] != cc:
            raise PopulationOverlapError(
                f"{prefix} ({cc}) is covered by {covering.prefix} "
                f"({covering.data['cc']}) - populations must be disjoint (D-016)"
            )
        for covered in self._tree.search_covered(prefix):
            if covered.data["cc"] != cc:
                raise PopulationOverlapError(
                    f"{prefix} ({cc}) covers {covered.prefix} "
                    f"({covered.data['cc']}) - populations must be disjoint (D-016)"
                )
        self._tree.add(prefix).data["cc"] = cc

    def match(self, prefix: str) -> str | None:
        """Return the covering population prefix for `prefix`, or None.

        Uses best-match (longest covering prefix), so more-specific announced
        prefixes match their delegated block.
        """
        node = self._search(prefix)
        return node.prefix if node else None

    def match_cc(self, prefix: str) -> tuple[str, str] | None:
        """Return (covering population prefix, country tag), or None."""
        node = self._search(prefix)
        return (node.prefix, node.data["cc"]) if node else None

    def _search(self, prefix: str):
        try:
            return self._tree.search_best(prefix)
        except ValueError:  # malformed prefix in the stream
            return None

    def __len__(self) -> int:
        return len(self._tree.nodes())
