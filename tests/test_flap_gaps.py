"""D-009: unit tests for the withdraw-then-reannounce gap computation."""

import pandas as pd
import pytest

from src.analysis import flap_gaps


def _events(rows):
    return pd.DataFrame(rows)


def test_gap_between_withdraw_and_next_announce_same_session():
    events = _events([
        dict(ts=100, prefix="a", cc="IR", asn=1, event="withdraw", peer_asn=2),
        dict(ts=160, prefix="a", cc="IR", asn=1, event="announce", peer_asn=2),
    ])
    gaps = flap_gaps.withdraw_reannounce_gaps(events)
    assert list(gaps) == [60]


def test_different_peers_are_independent_sessions():
    # Peer 2 withdraws, peer 3 (a DIFFERENT session) announces shortly after -
    # this is NOT a flap of peer 2's session, so it must not produce a gap.
    events = _events([
        dict(ts=100, prefix="a", cc="IR", asn=1, event="withdraw", peer_asn=2),
        dict(ts=110, prefix="a", cc="IR", asn=1, event="announce", peer_asn=3),
    ])
    gaps = flap_gaps.withdraw_reannounce_gaps(events)
    assert len(gaps) == 0


def test_announce_without_prior_withdraw_is_not_a_gap():
    events = _events([
        dict(ts=100, prefix="a", cc="IR", asn=1, event="announce", peer_asn=2),
    ])
    gaps = flap_gaps.withdraw_reannounce_gaps(events)
    assert len(gaps) == 0


def test_multiple_flaps_same_session_all_counted():
    events = _events([
        dict(ts=100, prefix="a", cc="IR", asn=1, event="withdraw", peer_asn=2),
        dict(ts=105, prefix="a", cc="IR", asn=1, event="announce", peer_asn=2),
        dict(ts=200, prefix="a", cc="IR", asn=1, event="withdraw", peer_asn=2),
        dict(ts=260, prefix="a", cc="IR", asn=1, event="announce", peer_asn=2),
    ])
    gaps = flap_gaps.withdraw_reannounce_gaps(events)
    assert sorted(gaps) == [5, 60]


def test_control_country_rows_excluded():
    events = _events([
        dict(ts=100, prefix="a", cc="TR", asn=9, event="withdraw", peer_asn=2),
        dict(ts=105, prefix="a", cc="TR", asn=9, event="announce", peer_asn=2),
    ])
    gaps = flap_gaps.withdraw_reannounce_gaps(events)
    assert len(gaps) == 0


def test_missing_cc_column_treated_as_all_ir():
    # Pre-D-016 event windows (e.g. feb2026_onset) have no cc column at all.
    events = pd.DataFrame([
        dict(ts=100, prefix="a", asn=1, event="withdraw", peer_asn=2),
        dict(ts=105, prefix="a", asn=1, event="announce", peer_asn=2),
    ])
    gaps = flap_gaps.withdraw_reannounce_gaps(events)
    assert list(gaps) == [5]


def test_flap_withdrawal_mask_flags_only_the_quick_reannounce_case():
    events = pd.DataFrame([
        dict(ts=100, prefix="a", cc="IR", asn=1, event="withdraw", peer_asn=2),  # flap (gap=5<=60)
        dict(ts=105, prefix="a", cc="IR", asn=1, event="announce", peer_asn=2),
        dict(ts=200, prefix="a", cc="IR", asn=1, event="withdraw", peer_asn=2),  # real (gap=300>60)
        dict(ts=500, prefix="a", cc="IR", asn=1, event="announce", peer_asn=2),
    ])
    mask = flap_gaps.flap_withdrawal_mask(events, flap_threshold_s=60)
    assert list(mask) == [True, False, False, False]


def test_flap_withdrawal_mask_boundary_is_inclusive():
    events = pd.DataFrame([
        dict(ts=100, prefix="a", cc="IR", asn=1, event="withdraw", peer_asn=2),
        dict(ts=160, prefix="a", cc="IR", asn=1, event="announce", peer_asn=2),  # gap=60
    ])
    assert list(flap_gaps.flap_withdrawal_mask(events, flap_threshold_s=60)) == [True, False]
    assert list(flap_gaps.flap_withdrawal_mask(events, flap_threshold_s=59)) == [False, False]


def test_drop_flap_withdrawals_removes_only_the_flap_withdraw_row():
    events = pd.DataFrame([
        dict(ts=100, prefix="a", cc="IR", asn=1, event="withdraw", peer_asn=2),  # flap
        dict(ts=105, prefix="a", cc="IR", asn=1, event="announce", peer_asn=2),
        dict(ts=200, prefix="a", cc="IR", asn=1, event="withdraw", peer_asn=2),  # real
    ])
    result = flap_gaps.drop_flap_withdrawals(events, flap_threshold_s=60)
    assert list(result["ts"]) == [105, 200]


def test_non_ir_rows_never_flagged_as_flaps():
    events = pd.DataFrame([
        dict(ts=100, prefix="a", cc="TR", asn=9, event="withdraw", peer_asn=2),
        dict(ts=105, prefix="a", cc="TR", asn=9, event="announce", peer_asn=2),
    ])
    mask = flap_gaps.flap_withdrawal_mask(events, flap_threshold_s=60)
    assert not mask.any()
