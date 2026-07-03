"""Radix-tree matching of observed BGP prefixes against the IR population.

An observed prefix matches if it equals, or is a more-specific of, a
delegated IR block (e.g. observed 5.22.192.0/21 inside delegated 5.22.192.0/17).
"""

from collections.abc import Iterable

import radix


class PrefixMatcher:
    """Wraps a radix tree of IR prefixes; supports IPv4 and IPv6."""

    def __init__(self, prefixes: Iterable[str]):
        self._tree = radix.Radix()
        for p in prefixes:
            self._tree.add(p)

    def match(self, prefix: str) -> str | None:
        """Return the covering IR prefix for `prefix`, or None.

        Uses best-match (longest covering prefix), so more-specific announced
        prefixes match their delegated block.
        """
        try:
            node = self._tree.search_best(prefix)
        except ValueError:  # malformed prefix in the stream
            return None
        return node.prefix if node else None

    def __len__(self) -> int:
        return len(self._tree.nodes())
