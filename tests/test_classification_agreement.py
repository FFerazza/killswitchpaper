import pandas as pd
import pytest

from src.analysis.classification_agreement import cohen_kappa, compare


def test_kappa_perfect_agreement():
    assert cohen_kappa(["a", "b", "a"], ["a", "b", "a"]) == 1.0


def test_kappa_known_value():
    # 2x2 example: po=0.8, pe=0.5 (balanced marginals) -> kappa=0.6
    a = ["x"] * 5 + ["y"] * 5
    b = ["x", "x", "x", "x", "y", "y", "y", "y", "y", "x"]
    assert cohen_kappa(a, b) == pytest.approx((0.8 - 0.5) / 0.5)


def test_kappa_rejects_length_mismatch():
    with pytest.raises(ValueError):
        cohen_kappa(["a"], ["a", "b"])


def _proposal():
    return pd.DataFrame({
        "asn": [1, 2, 3],
        "proposed_type": ["isp", "mobile", "financial"],
        "confidence": ["high", "high", "medium"],
    })


def _sample(types):
    return pd.DataFrame({
        "asn": [1, 2, 3],
        "org_name": ["A", "B", "C"],
        "ipv4_space": [10, 20, 30],
        "your_type": types,
        "your_confidence": ["high", "high", "high"],
    })


def test_compare_flags_disagreement():
    merged = compare(_proposal(), _sample(["isp", "isp", "financial"]))
    assert merged["agree"].tolist() == [True, False, True]


def test_compare_rejects_uncoded_rows():
    with pytest.raises(SystemExit, match="not fully coded"):
        compare(_proposal(), _sample(["isp", "", "financial"]))


def test_compare_rejects_sample_asn_missing_from_proposal():
    sample = _sample(["isp", "mobile", "financial"])
    sample.loc[2, "asn"] = 99
    with pytest.raises(SystemExit, match="missing from proposal"):
        compare(_proposal(), sample)
