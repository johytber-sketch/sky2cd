import warnings

from sky2cd.slots import build_mapping_report, resolve_slot


def test_slot_mapping_resolution_includes_mapped_merge_and_unsupported():
    mapped = resolve_slot("32")
    assert mapped.status == "mapped"
    assert mapped.cd_slot_name == "TorsoArmor"

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        merged = resolve_slot("34")
    assert merged.status == "merge"
    assert merged.merge_into == "Gloves"
    assert captured

    unsupported = resolve_slot("999")
    assert unsupported.status == "unsupported"

    report = build_mapping_report(["32", "34", "999"])
    assert len(report.mapped) == 1
    assert len(report.merged) == 1
    assert len(report.unsupported) == 1
