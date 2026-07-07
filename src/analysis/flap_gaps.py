"""D-009 (DECIDED, T=60s): withdraw-then-reannounce gaps and flap filtering.

Gaps/flaps are computed per (prefix, origin asn, peer_asn) - one BGP peer
session's view of one route. That is the standard level at which "flapping"
is defined (a specific session's route repeatedly withdrawn/re-announced);
computing it peer-agnostically (any withdraw anywhere followed by any
announce anywhere) would confuse ordinary cross-peer propagation-lag
differences - peer A withdrawing at t1 while peer B (which never actually
flapped) happens to send an unrelated announce at t2 - for a real flap.
"""

import pandas as pd


def _ir_updates(events: pd.DataFrame) -> pd.DataFrame:
    if "cc" in events.columns:
        events = events[events["cc"] == "IR"]
    return events[events["event"].isin(["announce", "withdraw"])][
        ["ts", "prefix", "asn", "peer_asn", "event"]
    ]


def withdraw_reannounce_gaps(events: pd.DataFrame) -> pd.Series:
    """Gap (seconds) between each withdraw and the next announce, per
    (prefix, asn, peer_asn) session - empty if that session never re-announces
    after a withdrawal in this window.
    """
    df = _ir_updates(events).sort_values(["prefix", "asn", "peer_asn", "ts"])
    grouped = df.groupby(["prefix", "asn", "peer_asn"], sort=False)
    prev_event = grouped["event"].shift()
    prev_ts = grouped["ts"].shift()
    is_reannounce = (df["event"] == "announce") & (prev_event == "withdraw")
    return (df.loc[is_reannounce, "ts"] - prev_ts[is_reannounce]).rename("gap_s")


def flap_withdrawal_mask(events: pd.DataFrame, flap_threshold_s: int) -> pd.Series:
    """D-009: boolean mask, aligned to `events`' original index, True for
    withdraw rows whose SAME peer session reannounces within
    `flap_threshold_s` - a flap, not a meaningful withdrawal for H4 onset
    metrics. Rows for non-IR cc or non-announce/withdraw events are always
    False (never filtered - only IR withdraw rows can be flagged).
    """
    df = _ir_updates(events).copy()
    df["_orig_index"] = df.index
    df = df.sort_values(["prefix", "asn", "peer_asn", "ts"])
    grouped = df.groupby(["prefix", "asn", "peer_asn"], sort=False)
    next_event = grouped["event"].shift(-1)
    next_ts = grouped["ts"].shift(-1)
    is_flap = (
        (df["event"] == "withdraw")
        & (next_event == "announce")
        & ((next_ts - df["ts"]) <= flap_threshold_s)
    )
    result = pd.Series(False, index=events.index)
    result.loc[df.loc[is_flap, "_orig_index"]] = True
    return result


def drop_flap_withdrawals(events: pd.DataFrame, flap_threshold_s: int) -> pd.DataFrame:
    """D-009: events with flap withdraw rows (see `flap_withdrawal_mask`)
    removed - the reannounce row that follows a flap is left in place
    (it's an ordinary announce, not itself a flap by this definition)."""
    return events[~flap_withdrawal_mask(events, flap_threshold_s)]
