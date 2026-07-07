"""IODA CLI: the per-ASN pull must cover the D-014 control population too,
not just the IR Stage 1 population (a 2026-07-06 full-crawl gap: the control
ASNs were never pulled, so inventory's ioda_asn check came up 30 short)."""

import yaml

from src.ioda.__main__ import load_control_asns


def test_missing_controls_file_yields_empty_list(tmp_path, monkeypatch):
    import src.ioda.__main__ as ioda_main

    monkeypatch.setattr(ioda_main, "CONFIG_DIR", tmp_path)
    assert load_control_asns() == []


def test_flattens_controls_yaml_across_countries(tmp_path, monkeypatch):
    import src.ioda.__main__ as ioda_main

    (tmp_path / "controls.yaml").write_text(yaml.dump({
        "asns": {"TR": [111, 222], "AE": [333], "PK": [444, 555]},
        "artifact_bin_share": 0.1,
    }))
    monkeypatch.setattr(ioda_main, "CONFIG_DIR", tmp_path)
    assert sorted(load_control_asns()) == [111, 222, 333, 444, 555]
