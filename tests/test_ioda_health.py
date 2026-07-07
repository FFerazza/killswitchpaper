"""QC checks for per-entity IODA pulls (native step, dedupe, coverage, cross-check)."""

import pandas as pd
import pytest

from src.analysis.ioda_health import cross_check, scan_file

START = 0
STEP = 300
END = 3000  # 10 native-step ticks: 0, 300, ..., 2700 (last = end - step)


def _rows(datasource="bgp", ticks=range(10), value=1.0, ts_step=STEP):
    return [
        {"ts": i * ts_step, "entity_type": "asn", "entity_code": "1", "datasource": datasource,
         "value": value}
        for i in ticks
    ]


def _write(tmp_path, rows, name="1.parquet"):
    path = tmp_path / name
    pd.DataFrame(rows, columns=["ts", "entity_type", "entity_code", "datasource", "value"]) \
        .to_parquet(path, index=False)
    return path


class TestScanFile:
    def test_healthy_full_grid_no_problems(self, tmp_path):
        path = _write(tmp_path, _rows())
        metrics, problems = scan_file(path, START, END)
        assert problems == []
        assert metrics["rows"] == 10
        assert metrics["steps"] == {"bgp": STEP}

    def test_zero_row_entity_not_flagged(self, tmp_path):
        path = _write(tmp_path, [])
        metrics, problems = scan_file(path, START, END)
        assert problems == []
        assert metrics["rows"] == 0

    def test_missing_columns_flagged(self, tmp_path):
        path = tmp_path / "bad.parquet"
        pd.DataFrame({"ts": [0], "value": [1.0]}).to_parquet(path, index=False)
        metrics, problems = scan_file(path, START, END)
        assert any("missing columns" in p for p in problems)

    def test_duplicate_ts_datasource_flagged(self, tmp_path):
        rows = _rows() + [_rows(ticks=[3])[0]]  # duplicate ts=900
        path = _write(tmp_path, rows)
        _, problems = scan_file(path, START, END)
        assert any("duplicate" in p for p in problems)

    def test_irregular_step_flagged(self, tmp_path):
        # drop tick 5 (ts=1500): leaves a gap that isn't a clean multiple issue
        # by itself, but inserting an off-grid point creates a non-multiple diff.
        rows = _rows(ticks=[0, 1, 2, 3, 4, 6, 7, 8, 9])  # missing tick 5
        rows.append({"ts": 1450, "entity_type": "asn", "entity_code": "1",
                     "datasource": "bgp", "value": 1.0})  # off-grid point
        path = _write(tmp_path, rows)
        _, problems = scan_file(path, START, END)
        assert any("irregular step" in p for p in problems)

    def test_coverage_gap_at_start_flagged(self, tmp_path):
        rows = _rows(ticks=range(1, 10))  # starts at ts=300, not 0
        path = _write(tmp_path, rows)
        _, problems = scan_file(path, START, END)
        assert any("coverage starts" in p for p in problems)

    def test_coverage_gap_at_end_flagged(self, tmp_path):
        rows = _rows(ticks=range(0, 9))  # ends at ts=2400, expected 2700
        path = _write(tmp_path, rows)
        _, problems = scan_file(path, START, END)
        assert any("coverage ends" in p for p in problems)

    def test_unreadable_file_flagged(self, tmp_path):
        path = tmp_path / "corrupt.parquet"
        path.write_bytes(b"not a parquet file")
        metrics, problems = scan_file(path, START, END)
        assert metrics["rows"] == 0
        assert any("unreadable" in p for p in problems)


class TestCrossCheck:
    def test_matching_values_no_problems(self, tmp_path):
        path = _write(tmp_path, _rows(), name="a.parquet")
        ref = _write(tmp_path, _rows(), name="b.parquet")
        assert cross_check(path, ref) == []

    def test_mismatched_values_flagged(self, tmp_path):
        path = _write(tmp_path, _rows(value=1.0), name="a.parquet")
        ref = _write(tmp_path, _rows(value=2.0), name="b.parquet")
        problems = cross_check(path, ref)
        assert problems and "10/10" in problems[0]

    def test_both_null_is_not_a_mismatch(self, tmp_path):
        rows = _rows(value=None)
        path = _write(tmp_path, rows, name="a.parquet")
        ref = _write(tmp_path, rows, name="b.parquet")
        assert cross_check(path, ref) == []

    def test_no_overlap_no_problems(self, tmp_path):
        path = _write(tmp_path, _rows(ticks=range(10)), name="a.parquet")
        ref = _write(tmp_path, _rows(ticks=range(100, 110)), name="b.parquet")
        assert cross_check(path, ref) == []
