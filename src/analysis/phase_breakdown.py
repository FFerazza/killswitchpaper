"""Per-phase H1/H2/H3 breakdown, parameterized by an explicit phase-boundary
dict rather than the fixed `config/phases.yaml` - lets a boundary sensitivity
sweep (D-025's pre-committed +/-24h check on the P1/P2 boundary) reuse the
exact same aggregation logic against shifted boundaries, instead of a fresh
one-off computation each time (the original 2026-07-06 P0-P4 breakdown that
produced the numbers in the killswitch-h1-finding memory was done this way -
ad hoc, not committed - this preserves that logic for reuse, per CLAUDE.md's
"no throwaway exploration whose logic isn't preserved").
"""

import pandas as pd

from src.analysis.flap_gaps import drop_flap_withdrawals
from src.common.config import Window


def _assign_phase(ts: pd.Series, phases: dict[str, Window]) -> pd.Series:
    """Half-open [start, end) phase assignment; ts outside every phase -> NA."""
    result = pd.Series(pd.NA, index=ts.index, dtype="object")
    for name, w in phases.items():
        mask = (ts >= w.start) & (ts < w.end)
        result[mask] = name
    return result


def dark_and_withdrawn_share(
    bgp_vs_ioda: pd.DataFrame, phases: dict[str, Window]
) -> pd.DataFrame:
    """H1: per-phase announced_but_dark / withdrawn share, over ALL (ts, asn)
    rows. D-013-inadequate ASNs default to `reachable` (can never register
    `announced_but_dark`), so this is a conservative lower bound on the true
    dark share, not a restricted-to-adequate-only computation.
    """
    df = bgp_vs_ioda.copy()
    df["phase"] = _assign_phase(df["ts"], phases)
    df = df.dropna(subset=["phase"])
    agg = df.groupby("phase").agg(
        dark_share=("state", lambda s: (s == "announced_but_dark").mean()),
        withdrawn_share=("state", lambda s: (s == "withdrawn").mean()),
        n=("state", "size"),
    )
    return agg.reindex(list(phases.keys()))


def transition_rate_by_phase(
    upstream_transitions: pd.DataFrame, phases: dict[str, Window]
) -> pd.DataFrame:
    """H2: per-phase upstream-set-change rate."""
    df = upstream_transitions.copy()
    df["phase"] = _assign_phase(df["ts"], phases)
    df = df.dropna(subset=["phase"])
    agg = df.groupby("phase").agg(
        transition_rate=("changed", "mean"),
        n=("changed", "size"),
    )
    return agg.reindex(list(phases.keys()))


def visibility_by_type_by_phase(
    visibility_by_type: pd.DataFrame, phases: dict[str, Window]
) -> pd.DataFrame:
    """H3: per-phase visibility_mean by classification type.

    Matches the ORIGINAL two-stage aggregation order used in the
    2026-07-06 independent re-verification: `visibility_by_type` already
    holds one mean per (ts, type); this takes the mean of THOSE means per
    phase, rather than re-aggregating from raw visibility rows. The two
    orders disagree at the 3rd decimal (found during that re-verification) -
    matching the original order exactly is required for a real comparison,
    not just using the same groupby key.
    """
    df = visibility_by_type.copy()
    df["phase"] = _assign_phase(df["ts"], phases)
    df = df.dropna(subset=["phase"])
    agg = (
        df.groupby(["phase", "type"])["visibility_mean"]
        .mean()
        .reset_index()
        .pivot(index="phase", columns="type", values="visibility_mean")
        .reindex(list(phases.keys()))
    )
    return agg


def shifted_phases(phases: dict[str, Window], boundary: str, shift_seconds: int) -> dict[str, Window]:
    """Shift a single named phase boundary (e.g. the shared P1/P2 instant)
    by `shift_seconds`, keeping every other boundary fixed. `boundary` is the
    name of the phase whose END moves; the next phase (by dict order) has its
    START moved to match, so the two stay contiguous (no gap or overlap).
    """
    names = list(phases.keys())
    i = names.index(boundary)
    if i + 1 >= len(names):
        raise ValueError(f"{boundary!r} has no following phase to stay contiguous with")
    new_instant = phases[boundary].end + shift_seconds
    out = dict(phases)
    left, right = names[i], names[i + 1]
    out[left] = Window(name=left, start=phases[left].start, end=new_instant)
    out[right] = Window(name=right, start=new_instant, end=phases[right].end)
    return out


def boundary_sensitivity_sweep(
    bgp_vs_ioda: pd.DataFrame,
    upstream_transitions: pd.DataFrame,
    phases: dict[str, Window],
    boundary: str,
    shifts_seconds: list[int],
) -> pd.DataFrame:
    """D-025 robustness: recompute H1/H2 for the two phases straddling
    `boundary` under a range of shifts, rather than a single pre-chosen
    perturbation size.

    D-025's original pre-committed check (inherited from D-001's robustness
    note, written when phase boundaries were coarse press-reported dates) was
    a single +/-24h test. That figure was never revalidated against how
    narrow P2 ended up being (16.2h) once D-025 timed it to native IODA
    resolution - a flat +/-24h shift exceeds P2's own width, so it either
    swallows most of P2 or (shifted the other way) pushes P2's start past
    its own end, making the phase empty. A sweep across shift sizes actually
    scaled to the measured transition duration (~40min, per the independently
    verified onset timing) shows where the metric is genuinely stable versus
    where it mechanically breaks down from the bucket vanishing - both are
    informative, neither should be hidden behind one arbitrarily-picked point.

    The two straddling phases are identified by name (`boundary` and its
    successor in `phases`' insertion order) so callers don't need to know
    that convention themselves.
    """
    names = list(phases.keys())
    i = names.index(boundary)
    left, right = names[i], names[i + 1]

    rows = []
    for shift in shifts_seconds:
        p = phases if shift == 0 else shifted_phases(phases, boundary, shift)
        h1 = dark_and_withdrawn_share(bgp_vs_ioda, p)
        h2 = transition_rate_by_phase(upstream_transitions, p)
        row = {"shift_s": shift}
        for name in (left, right):
            # dark_and_withdrawn_share/transition_rate_by_phase reindex to
            # every phase name, so an emptied-out phase (e.g. P2 pushed past
            # its own end) is still present as a row of NaNs, not a missing
            # label - NaN IS the correct "no data" signal here, not 0.
            row[f"{name}_dark_share"] = h1.loc[name, "dark_share"]
            row[f"{name}_withdrawn_share"] = h1.loc[name, "withdrawn_share"]
            row[f"{name}_transition_rate"] = h2.loc[name, "transition_rate"]
            row[f"{name}_n"] = h1.loc[name, "n"]
        rows.append(row)
    return pd.DataFrame(rows)


def snapshot_trajectory(bgp_vs_ioda: pd.DataFrame, ts_list: list[int]) -> pd.DataFrame:
    """Raw per-snapshot dark_share/withdrawn_share for specific timestamps,
    with no phase-bucketing at all.

    D-025's boundary sweep found the P1/P2 boundary sits in an 8h-gridded
    primary series where P2 (16.2h wide) is sampled by only 2 snapshots -
    any "phase mean" here is really just the mean of 2 numbers, and a
    continuous +/-Xh sweep either changes nothing (shift doesn't cross a
    snapshot) or jumps discretely (it does). The more honest and more
    informative report is the raw trajectory across the transition, not a
    sweep of an average that was never smooth to begin with.
    """
    rows = []
    for t in ts_list:
        sub = bgp_vs_ioda[bgp_vs_ioda["ts"] == t]
        rows.append({
            "ts": t,
            "dark_share": (sub["state"] == "announced_but_dark").mean(),
            "withdrawn_share": (sub["state"] == "withdrawn").mean(),
            "n": len(sub),
        })
    return pd.DataFrame(rows)


def withdrawal_wave_timing(
    events: pd.DataFrame, phase_start: int, flap_threshold_s: int
) -> dict:
    """Percentiles of per-prefix first-withdrawal time, restricted to
    withdrawals AT OR AFTER an already-decided phase boundary (e.g. P2's
    start).

    Event-window pulls intentionally include a quiet buffer day before the
    boundary they target (margin for the pull, not part of the phase), so
    naive percentiles over the WHOLE event window are contaminated by
    ordinary pre-onset background churn - the unscoped p5 for feb2026_onset
    lands 7+ hours before the boundary, clearly not "the wave." Restricting
    to ts >= phase_start uses only the boundary decision already made
    (D-025), not a new threshold, and recovers a clean, tight wave onset.
    """
    if "cc" in events.columns:
        events = events[events["cc"] == "IR"]
    events = drop_flap_withdrawals(events, flap_threshold_s)
    withdrawals = events[(events["event"] == "withdraw") & (events["ts"] >= phase_start)]
    first_w = withdrawals.groupby("prefix")["ts"].min()
    return {
        "n_prefixes": int(first_w.size),
        "t_min": int(first_w.min()),
        "t_p5": int(first_w.quantile(0.05)),
        "t_p50": int(first_w.quantile(0.50)),
        "t_p95": int(first_w.quantile(0.95)),
    }
