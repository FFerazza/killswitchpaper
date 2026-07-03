"""D-014 control population: org-ranked selection and the artifact-share check."""

import pandas as pd
import pytest

from src.analysis.controls import control_dark_shares
from src.population.controls import org_ranked_asns

DELEGATION_FIXTURE = """\
2|ripencc|20260101|4|4|4|+0000
ripencc|TR|ipv4|10.0.0.0|65536|20200101|allocated|org-big
ripencc|TR|asn|64500|2|20200101|allocated|org-big
ripencc|TR|ipv4|10.9.0.0|256|20200101|allocated|org-small
ripencc|TR|asn|64510|1|20200101|allocated|org-small
ripencc|TR|asn|64520|1|20200101|reserved|org-ignored
ripencc|AE|asn|64600|1|20200101|allocated|org-other-cc
"""


class TestOrgRankedAsns:
    def test_orders_by_org_space_and_expands_asn_ranges(self):
        ranked = org_ranked_asns(DELEGATION_FIXTURE.splitlines(), "TR")
        assert ranked == [(64500, 65536), (64501, 65536), (64510, 256)]

    def test_filters_country_and_status(self):
        ranked = org_ranked_asns(DELEGATION_FIXTURE.splitlines(), "AE")
        assert ranked == [(64600, 0)]


def _write_signal(directory, asn, ts_values):
    directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "ts": [t for t, _ in ts_values],
        "entity_type": "asn",
        "entity_code": str(asn),
        "datasource": "ping-slash24",
        "value": [v for _, v in ts_values],
    }).to_parquet(directory / f"{asn}.parquet", index=False)


class TestControlDarkShares:
    ADEQUACY = {"min_nonzero_share": 0.5, "min_median": 5}

    def test_healthy_controls_yield_zero_dark_share(self, tmp_path):
        baseline = tmp_path / "baseline"
        live = tmp_path / "live"
        for asn in (64500, 64510):
            _write_signal(baseline, asn, [(i, 100.0) for i in range(10)])
            _write_signal(live, asn, [(1000, 95.0), (2000, 105.0)])
        shares = control_dark_shares(
            {"TR": [64500, 64510]}, live, baseline, [1000, 2000],
            probing_dark_ratio=0.2, probing_adequacy=self.ADEQUACY,
        )
        assert list(shares.dark_share) == [0.0, 0.0]
        assert list(shares.n_controls) == [2, 2]

    def test_collapsed_control_is_counted_dark(self, tmp_path):
        baseline = tmp_path / "baseline"
        live = tmp_path / "live"
        _write_signal(baseline, 64500, [(i, 100.0) for i in range(10)])
        _write_signal(live, 64500, [(1000, 100.0), (2000, 1.0)])
        shares = control_dark_shares(
            {"TR": [64500]}, live, baseline, [1000, 2000],
            probing_dark_ratio=0.2, probing_adequacy=self.ADEQUACY,
        )
        assert list(shares.dark_share) == [0.0, 1.0]

    def test_inadequate_controls_are_excluded(self, tmp_path):
        baseline = tmp_path / "baseline"
        live = tmp_path / "live"
        _write_signal(baseline, 64500, [(i, 0.0) for i in range(9)] + [(9, 100.0)])
        _write_signal(live, 64500, [(1000, 0.0)])
        with pytest.raises(SystemExit, match="no control observations"):
            control_dark_shares(
                {"TR": [64500]}, live, baseline, [1000],
                probing_dark_ratio=0.2, probing_adequacy=self.ADEQUACY,
            )
