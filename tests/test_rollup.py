"""D-022: unit tests for the address-space-weighted rollup, small fixtures."""

import pandas as pd
import pytest

from src.common import rollup


def _vis(rows):
    return pd.DataFrame(rows, columns=["ts", "prefix", "visibility"])


def _blocks(rows):
    return pd.DataFrame(rows, columns=["prefix", "family"])


def test_exact_match_reduces_to_plain_visibility():
    # observed prefix == delegated block -> weighted visibility is just the
    # per-prefix visibility (no more-specific splitting).
    vis = _vis([(1000, "5.22.0.0/16", 0.75)])
    blocks = _blocks([("5.22.0.0/16", 4)])
    result = rollup.rollup_visibility(vis, blocks)
    row = result.iloc[0]
    assert row.prefix == "5.22.0.0/16"
    assert row.visibility_weighted == pytest.approx(0.75)
    assert row.visibility_max == pytest.approx(0.75)
    assert row.n_observed == 1


def test_single_restored_subprefix_is_a_small_fraction_of_a_larger_block():
    # A /24 (1/256 of a /16) comes back fully visible: the block-level
    # weighted visibility must reflect "a sliver came back," not "restored."
    vis = _vis([(1000, "5.22.7.0/24", 1.0)])
    blocks = _blocks([("5.22.0.0/16", 4)])
    result = rollup.rollup_visibility(vis, blocks)
    row = result.iloc[0]
    assert row.prefix == "5.22.0.0/16"
    assert row.visibility_weighted == pytest.approx(1 / 256)
    assert row.visibility_max == pytest.approx(1.0)  # companion metric: "is any of it back"


def test_multiple_covered_prefixes_sum_weighted_by_size():
    # Two /24s (each 1/256) at different visibility, one /23 (1/128) as well;
    # all inside the same /16.
    vis = _vis([
        (1000, "5.22.1.0/24", 1.0),
        (1000, "5.22.2.0/24", 0.5),
        (1000, "5.22.4.0/23", 1.0),
    ])
    blocks = _blocks([("5.22.0.0/16", 4)])
    result = rollup.rollup_visibility(vis, blocks)
    row = result.iloc[0]
    expected = (1.0 / 256 + 0.5 / 256 + 1.0 / 128)
    assert row.visibility_weighted == pytest.approx(expected)
    assert row.n_observed == 3


def test_blocks_are_kept_independent():
    vis = _vis([
        (1000, "5.22.0.0/16", 1.0),
        (1000, "8.8.0.0/16", 0.0),
    ])
    blocks = _blocks([("5.22.0.0/16", 4), ("8.8.0.0/16", 4)])
    result = rollup.rollup_visibility(vis, blocks)
    result = result.set_index("prefix")
    assert result.loc["5.22.0.0/16", "visibility_weighted"] == pytest.approx(1.0)
    assert result.loc["8.8.0.0/16", "visibility_weighted"] == pytest.approx(0.0)


def test_uncovered_observed_prefix_raises():
    vis = _vis([(1000, "9.9.9.0/24", 1.0)])
    blocks = _blocks([("5.22.0.0/16", 4)])
    with pytest.raises(ValueError, match="no covering delegated block"):
        rollup.rollup_visibility(vis, blocks)


def test_missing_ts_block_pair_means_fully_withdrawn():
    # A block with zero observed announcements at some ts is simply absent
    # from the output - callers treat that as visibility 0 (same convention
    # as the per-AS withdrawn state elsewhere).
    vis = _vis([(1000, "5.22.0.0/16", 1.0)])
    blocks = _blocks([("5.22.0.0/16", 4), ("8.8.0.0/16", 4)])
    result = rollup.rollup_visibility(vis, blocks)
    assert set(result["prefix"]) == {"5.22.0.0/16"}


def test_overlapping_aggregate_and_subprefix_not_double_counted():
    # Real routing tables often announce a block AND a more-specific inside
    # it simultaneously (deaggregation for TE/multihoming). The /16 aggregate
    # (visibility 0.9) fully covers a /24 inside it (visibility 1.0) - the
    # /24's address space must be attributed ONLY to the /24 (most specific),
    # not counted again via the /16. Without this, weighted visibility could
    # exceed 1.0, which is impossible for a fraction - this reproduces a bug
    # found on real data (some blocks' P0 baseline came out above 1.0).
    vis = _vis([
        (1000, "5.22.0.0/16", 0.9),
        (1000, "5.22.7.0/24", 1.0),
    ])
    blocks = _blocks([("5.22.0.0/16", 4)])
    result = rollup.rollup_visibility(vis, blocks)
    row = result.iloc[0]
    rest_of_block = 1 - 1 / 256
    expected = rest_of_block * 0.9 + (1 / 256) * 1.0
    assert expected <= 1.0
    assert row.visibility_weighted == pytest.approx(expected)
    assert row.visibility_weighted <= 1.0


def test_deeply_nested_overlap_still_bounded_by_one():
    # /17 (0.9) contains /19 (0.95) contains /22 (1.0) - three levels of
    # nesting, mirroring the real /17 case found in the data (rrc/collector
    # announcing an aggregate plus several levels of more-specifics at once).
    vis = _vis([
        (1000, "5.22.0.0/17", 0.9),
        (1000, "5.22.0.0/19", 0.95),
        (1000, "5.22.0.0/22", 1.0),
    ])
    blocks = _blocks([("5.22.0.0/17", 4)])
    result = rollup.rollup_visibility(vis, blocks)
    row = result.iloc[0]
    assert row.visibility_weighted <= 1.0
    # exclusive shares: /17 minus /19's span, /19 minus /22's span, /22 whole
    frac_19_of_17 = 1 / 4    # /19 is 1/4 of a /17
    frac_22_of_17 = 1 / 32   # /22 is 1/32 of a /17
    expected = (
        (1 - frac_19_of_17) * 0.9
        + (frac_19_of_17 - frac_22_of_17) * 0.95
        + frac_22_of_17 * 1.0
    )
    assert row.visibility_weighted == pytest.approx(expected)


def test_disjoint_subprefixes_still_sum_normally():
    # Two non-overlapping /24s inside a /16 - no nesting between them, so
    # this must behave exactly like the pre-overlap-fix simple sum.
    vis = _vis([
        (1000, "5.22.1.0/24", 1.0),
        (1000, "5.22.2.0/24", 0.5),
    ])
    blocks = _blocks([("5.22.0.0/16", 4)])
    result = rollup.rollup_visibility(vis, blocks)
    row = result.iloc[0]
    assert row.visibility_weighted == pytest.approx(1.0 / 256 + 0.5 / 256)
