"""D-012 two-series robustness exhibit (argument 3 of
paper-two-series-justification, FF-approved 2026-07-05): visibility is
bimodal (~1.0 announced / ~0.0 withdrawn), so a 0.5 threshold reads the same
whether from the primary series' 118 observers or the RIS-secondary's ~380 -
extra vantage points only matter in a partial-propagation regime, which is
exactly what the ex-ante-sampled hotspot windows exist to catch. This
DEMONSTRATES that claim on the actual overlapping data rather than asserting
it: the two series are compared at their shared snapshots, never merged.
"""

import pandas as pd

from src.analysis.joins import drop_degraded


def visibility_distribution_comparison(
    primary: pd.DataFrame,
    ris: pd.DataFrame,
    min_fullfeed_peers: int,
    ambiguous_band: tuple[float, float] = (0.1, 0.9),
    cc: str = "IR",
) -> pd.DataFrame:
    """Per-observed-prefix visibility values from both series, restricted to
    their overlapping snapshots (the RIS series only covers the ex-ante
    hotspot windows, so this is never the full study period) - tidy output,
    one row per (series, ts, prefix), ready for a histogram/overlay figure.

    Both series get the same D-020 degraded-cell filter and the same `cc`
    restriction, so neither one's own coverage quirks bias the comparison.
    Degraded-cell filtering happens BEFORE the overlap is computed: if
    either series is degraded at a given ts, that moment isn't a valid
    PAIRED comparison point (one side's value there is known-unreliable),
    so it's dropped from both, not just the degraded side.
    """
    primary = drop_degraded(primary, min_fullfeed_peers)
    ris = drop_degraded(ris, min_fullfeed_peers)
    primary = primary[primary["cc"] == cc]
    ris = ris[ris["cc"] == cc]

    shared_ts = set(primary["ts"].unique()) & set(ris["ts"].unique())
    primary = primary[primary["ts"].isin(shared_ts)].assign(series="primary")
    ris = ris[ris["ts"].isin(shared_ts)].assign(series="ris")

    cols = ["ts", "prefix", "family", "visibility", "series"]
    return pd.concat([primary[cols], ris[cols]], ignore_index=True)


def bimodality_summary(
    comparison: pd.DataFrame, ambiguous_band: tuple[float, float] = (0.1, 0.9)
) -> pd.DataFrame:
    """Per series: fraction of visibility values falling INSIDE the
    "ambiguous middle" band vs outside it (near 0 or near 1). Small and
    similar fractions in both series is the concrete number backing
    "bimodal, threshold-insensitive" - not just a histogram shape claim.
    """
    lo, hi = ambiguous_band
    in_band = comparison["visibility"].between(lo, hi)
    return (
        comparison.assign(ambiguous=in_band)
        .groupby("series")
        .agg(
            n=("visibility", "size"),
            ambiguous_share=("ambiguous", "mean"),
            near_zero_share=("visibility", lambda s: (s <= lo).mean()),
            near_one_share=("visibility", lambda s: (s >= hi).mean()),
        )
        .reset_index()
    )
