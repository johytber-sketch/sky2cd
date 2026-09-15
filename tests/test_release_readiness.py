from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_third_party_notice_and_license_are_present():
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    license_text = (
        ROOT / "src" / "sky2cd" / "vendor" / "io_scene_nifly" / "LICENSE"
    ).read_text(encoding="utf-8")

    assert "GPL-3.0-only" in notice
    assert "Public binary release blocker" in notice
    assert "NiflyDLL.dll" in notice
    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 29 June 2007" in license_text


def test_windows_build_excludes_unverified_vendored_assets():
    script = (ROOT / "build_exe.ps1").read_text(encoding="utf-8")

    assert '$VendorPynSource' in script
    assert '$VendorDllSource' in script
    assert '$VendorLicenseSource' in script
    assert '$NoticesSource' in script
    assert '--add-data "$VendorSource;$VendorTarget"' not in script
    assert "skeletons" not in script
    assert "blender_assets" not in script
    assert "hkxcmd.exe" not in script


def test_example_workflow_is_placeholder_only_and_preserves_boundary():
    example = (ROOT / "docs" / "EXAMPLE_WORKFLOW.md").read_text(encoding="utf-8")

    assert "<YOUR_OWN_DRESS_PIECE>" in example
    assert "donor_suggestion.json" in example
    assert "Blender" in example
    assert "does not validate fit" in example
    assert "game-ready" in example
    assert not any(
        path.suffix.lower() in {".nif", ".dds", ".hkx", ".blend", ".pac"}
        for path in (ROOT / "docs").rglob("*")
        if path.is_file()
    )
