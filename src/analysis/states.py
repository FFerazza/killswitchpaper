"""Per-AS state derivation for H1 (mechanism: filtering vs control-plane withdrawal).

States:
    announced_and_reachable  routes visible AND active probing near baseline
    announced_but_dark       routes visible BUT probing collapsed (=> filtering)
    withdrawn                routes not visible (=> control-plane withdrawal)
"""

ANNOUNCED_AND_REACHABLE = "announced_and_reachable"
ANNOUNCED_BUT_DARK = "announced_but_dark"
WITHDRAWN = "withdrawn"


def derive_state(
    visibility: float,
    probing: float | None,
    probing_baseline: float | None,
    visibility_announced_min: float,
    probing_dark_ratio: float,
) -> str:
    """Classify one (AS, time-bin) observation.

    `probing` is the active-probing signal value; `probing_baseline` its
    pre-shutdown baseline for the same AS. If either is missing (signal gap
    or AS not covered by probing), an announced AS is conservatively labeled
    announced_and_reachable — darkness requires positive evidence.
    """
    if visibility < visibility_announced_min:
        return WITHDRAWN
    if probing is None or probing_baseline is None or probing_baseline <= 0:
        return ANNOUNCED_AND_REACHABLE
    if probing < probing_dark_ratio * probing_baseline:
        return ANNOUNCED_BUT_DARK
    return ANNOUNCED_AND_REACHABLE
