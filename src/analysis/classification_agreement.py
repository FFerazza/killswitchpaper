"""D-018 validation: agreement between FF's blind coding and the proposal.

FF independently codes a stratified sample of proposal rows (blind to the
proposed types); this script computes percent agreement and Cohen's kappa
between the two codings, per D-018 (5). kappa < 0.7 means the coding rules
must be revised and the proposal re-coded before H3 runs.

Usage:
    python -m src.analysis.classification_agreement [--sample PATH]
Output:
    outputs/classification_agreement.csv (per-row comparison) + metrics logged.
"""

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd

from src.common.config import OUTPUTS_DIR
from src.common.log import get_logger

log = get_logger("analysis.classification_agreement")

KAPPA_THRESHOLD = 0.7  # D-018 (5)

DEFAULT_SAMPLE = OUTPUTS_DIR / "asn_classification_blind_sample_round2.csv"
PROPOSAL = OUTPUTS_DIR / "asn_classification_proposal.csv"


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Cohen's kappa for two label sequences of equal length."""
    if len(a) != len(b) or not a:
        raise ValueError("label sequences must be equal-length and non-empty")
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb.get(k, 0) for k in ca) / (n * n)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def compare(proposal: pd.DataFrame, sample: pd.DataFrame) -> pd.DataFrame:
    """Join FF's blind codes onto the proposal rows they sampled."""
    prop = proposal[["asn", "proposed_type", "confidence"]].drop_duplicates("asn")
    merged = sample.merge(prop, on="asn", how="left", validate="one_to_one")
    missing = merged[merged["proposed_type"].isna()]
    if not missing.empty:
        raise SystemExit(
            f"sample ASNs missing from proposal: {sorted(missing['asn'])}"
        )
    uncoded = merged[merged["your_type"].isna() | (merged["your_type"] == "")]
    if not uncoded.empty:
        raise SystemExit(
            f"blind sample not fully coded yet (empty your_type): "
            f"{sorted(uncoded['asn'])}"
        )
    merged["agree"] = merged["your_type"] == merged["proposed_type"]
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    args = parser.parse_args()

    proposal = pd.read_csv(PROPOSAL)
    sample = pd.read_csv(args.sample)
    merged = compare(proposal, sample)

    agreement = float(merged["agree"].mean())
    kappa = cohen_kappa(
        merged["your_type"].tolist(), merged["proposed_type"].tolist()
    )

    out = OUTPUTS_DIR / "classification_agreement.csv"
    merged.to_csv(out, index=False)
    summary = pd.DataFrame([{
        "n": len(merged),
        "n_agree": int(merged["agree"].sum()),
        "percent_agreement": round(agreement, 4),
        "cohen_kappa": round(kappa, 4),
        "kappa_threshold": KAPPA_THRESHOLD,
        "gate_passed": bool(kappa >= KAPPA_THRESHOLD),
        "sample_file": args.sample.name,
    }])
    summary_out = OUTPUTS_DIR / "classification_agreement_summary.csv"
    summary.to_csv(summary_out, index=False)

    for r in merged[~merged["agree"]].itertuples():
        log.info("DISAGREE AS%d %s: FF=%s vs proposal=%s (conf %s/%s)",
                 r.asn, r.org_name, r.your_type, r.proposed_type,
                 r.your_confidence, r.confidence)
    log.info("n=%d  agreement=%.3f  kappa=%.3f -> %s", len(merged),
             agreement, kappa, out)
    if kappa < KAPPA_THRESHOLD:
        log.warning("kappa %.3f < %.1f: revise coding rules and re-code "
                    "before H3 (D-018)", kappa, KAPPA_THRESHOLD)
    else:
        log.info("kappa %.3f >= %.1f: D-018 validation gate PASSED",
                 kappa, KAPPA_THRESHOLD)


if __name__ == "__main__":
    main()
