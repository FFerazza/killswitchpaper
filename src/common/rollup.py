"""D-022: address-space-weighted rollup of observed-prefix visibility to
delegated blocks.

`src/bgp/ribs.py::process_snapshot` already assumes every observed BGP
announcement equals, or is a more-specific of, exactly one delegated block
(see `PrefixMatcher`'s docstring) - that assumption is reused here rather
than re-derived: each observed prefix maps to exactly one covering block via
longest-prefix match, never split across several.

Real routing tables commonly announce a block AND more-specifics inside it
simultaneously (deaggregation for traffic engineering / multihoming) - e.g.
a /17 alongside overlapping /19s and /24s within it, all observed at the
same snapshot. Naively summing size(p) * visibility(p) over every observed
prefix covered by a block double- (or many-times-) counts that overlapping
address space; verified on real data (some blocks' P0 baseline came out
above 1.0, which is impossible for a visibility fraction). `_seen_space`
resolves this via longest-prefix-match: an address covered by several
nested observed announcements is attributed only to the most specific one.
"""

import ipaddress
from collections.abc import Iterable

import pandas as pd
import radix


def prefix_size(prefix: str) -> int:
    return ipaddress.ip_network(prefix, strict=False).num_addresses


def _prefix_bounds(prefix: str) -> tuple[int, int]:
    net = ipaddress.ip_network(prefix, strict=False)
    start = int(net.network_address)
    return start, start + net.num_addresses


def _block_tree(delegated_prefixes: Iterable[str]) -> radix.Radix:
    tree = radix.Radix()
    for p in delegated_prefixes:
        tree.add(p)
    return tree


def map_to_blocks(
    observed_prefixes: Iterable[str], delegated_prefixes: Iterable[str]
) -> dict[str, str]:
    """Map each observed prefix to its covering delegated block (best match).

    Raises if an observed prefix has no covering block - that would mean a
    prefix entered the visibility series without having matched the same
    population tree at collection time (a data-consistency bug, not a case
    to silently skip).
    """
    tree = _block_tree(delegated_prefixes)
    out: dict[str, str] = {}
    for p in observed_prefixes:
        node = tree.search_best(p)
        if node is None:
            raise ValueError(f"observed prefix {p!r} has no covering delegated block")
        out[p] = node.prefix
    return out


def _seen_space(sorted_rows: pd.DataFrame) -> pd.DataFrame:
    """`sorted_rows` must have columns (ts, block, start, end, visibility),
    sorted by (ts, block, start asc, end desc).

    Single linear pass, one stack of "open" ancestor intervals per (ts,
    block) group. CIDR blocks never partially overlap (a fundamental
    property of CIDR: any two ranges are either nested or disjoint), so
    under this sort order the stack top is always the true immediate parent
    of the next row - no need to search for it. Each finalized interval
    contributes (own size - size already claimed by its present children) *
    its own visibility, and its own full size is credited to its parent's
    "claimed" tally (using the full span, not just its own exclusive part,
    since the child's descendants are already inside that span).

    Runs as one O(N) pass with an explicit stack rather than
    `groupby().apply()`, which would pay Python call overhead per group
    across the ~2.6M (ts, block) groups in the full study period.
    """
    ts_arr = sorted_rows["ts"].to_numpy()
    block_arr = sorted_rows["block"].to_numpy()
    start_arr = sorted_rows["start"].to_numpy()
    end_arr = sorted_rows["end"].to_numpy()
    vis_arr = sorted_rows["visibility"].to_numpy()

    results: list[tuple] = []
    stack: list[list] = []  # [start, end, visibility, covered_by_children]
    cur_key = None
    total = 0.0

    def close_stack() -> None:
        nonlocal total
        while stack:
            s, e, v, covered = stack.pop()
            total += (e - s - covered) * v
            if stack:
                stack[-1][3] += e - s

    for i in range(len(sorted_rows)):
        key = (ts_arr[i], block_arr[i])
        if key != cur_key:
            if cur_key is not None:
                close_stack()
                results.append((*cur_key, total))
            cur_key = key
            stack = []
            total = 0.0
        start, end, vis = start_arr[i], end_arr[i], vis_arr[i]
        while stack and stack[-1][1] <= start:
            s, e, v, covered = stack.pop()
            total += (e - s - covered) * v
            if stack:
                stack[-1][3] += e - s
        stack.append([start, end, vis, 0])
    if cur_key is not None:
        close_stack()
        results.append((*cur_key, total))

    return pd.DataFrame(results, columns=["ts", "block", "seen_space"])


def rollup_visibility(
    visibility: pd.DataFrame, delegated: pd.DataFrame
) -> pd.DataFrame:
    """D-022: per (ts, delegated block), address-space-weighted visibility.

    `visibility` is the per-observed-prefix series (ts, prefix, visibility, ...);
    `delegated` has columns (prefix, family) - the delegated blocks (e.g.
    `data/population/ir_prefixes.csv`).

    Returns one row per (ts, block) that has >=1 observed prefix at that ts:
        visibility_weighted = seen address space (LPM-resolved, no double-
                               counting of overlapping/deaggregated routes)
                               / size(block)
        visibility_max      = max(visibility(p) for p covered by block)   [D-022 companion metric]
        n_observed          = count of distinct observed prefixes covered

    A block absent from the output at a given ts had zero observed
    announcements there - callers should treat that as visibility 0 (same
    convention as the per-AS `withdrawn` state elsewhere in this pipeline).
    """
    unique_prefixes = visibility["prefix"].unique()
    mapping = map_to_blocks(unique_prefixes, delegated["prefix"])
    bounds = {p: _prefix_bounds(p) for p in unique_prefixes}
    block_info = delegated.assign(size=delegated["prefix"].map(prefix_size)).set_index("prefix")

    df = visibility[["ts", "prefix", "visibility"]].copy()
    df["block"] = df["prefix"].map(mapping)
    df["start"] = df["prefix"].map(lambda p: bounds[p][0])
    df["end"] = df["prefix"].map(lambda p: bounds[p][1])

    simple = (
        df.groupby(["ts", "block"])
        .agg(visibility_max=("visibility", "max"), n_observed=("prefix", "nunique"))
        .reset_index()
    )

    ordered = df.sort_values(
        ["ts", "block", "start", "end"], ascending=[True, True, True, False]
    )
    seen = _seen_space(ordered)

    agg = simple.merge(seen, on=["ts", "block"], how="left")
    agg["block_size"] = agg["block"].map(block_info["size"])
    agg["family"] = agg["block"].map(block_info["family"])
    agg["visibility_weighted"] = agg["seen_space"] / agg["block_size"]
    return agg.drop(columns=["seen_space", "block_size"]).rename(columns={"block": "prefix"})
