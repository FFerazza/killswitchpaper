"""Unit tests for the classification merge - manual entries must survive."""

from src.population.classification import merge_classification


def test_new_asns_prefilled_with_blank_type():
    rows = merge_classification({}, [100, 200], {100: "Org A", 200: "Org B"})
    assert rows == [
        {"asn": "100", "org_name": "Org A", "type": "", "notes": ""},
        {"asn": "200", "org_name": "Org B", "type": "", "notes": ""},
    ]


def test_manual_type_and_notes_never_overwritten():
    existing = {
        100: {"asn": "100", "org_name": "Org A", "type": "state_telecom", "notes": "TIC"},
    }
    rows = merge_classification(existing, [100], {100: "New Org Name"})
    assert rows[0]["type"] == "state_telecom"
    assert rows[0]["notes"] == "TIC"
    # org_name already set manually/previously -> kept, not replaced
    assert rows[0]["org_name"] == "Org A"


def test_blank_org_name_is_filled():
    existing = {100: {"asn": "100", "org_name": "", "type": "isp", "notes": ""}}
    rows = merge_classification(existing, [100], {100: "Filled Org"})
    assert rows[0]["org_name"] == "Filled Org"
    assert rows[0]["type"] == "isp"


def test_rows_for_departed_asns_are_kept():
    existing = {999: {"asn": "999", "org_name": "Gone Org", "type": "other", "notes": "x"}}
    rows = merge_classification(existing, [100], {100: "Org A"})
    asns = [r["asn"] for r in rows]
    assert asns == ["100", "999"]  # sorted, departed ASN retained


def test_output_sorted_by_asn():
    rows = merge_classification({}, [300, 100, 200], {})
    assert [r["asn"] for r in rows] == ["100", "200", "300"]
