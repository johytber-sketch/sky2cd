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


def test_user_guide_documents_key_workflows_and_boundary():
    guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")

    # Install/no-Python-required messaging.
    assert "do not need to install Python separately" in guide
    assert "sky2cd-gui.exe" in guide and "sky2cd.exe" in guide

    # Core workflows covered.
    assert "Dark mode" in guide
    assert "blender-handoff" in guide
    assert "--suggest-out" in guide
    assert "package-dmm" in guide

    # Troubleshooting coverage.
    assert "SmartScreen" in guide
    assert "Fully close every open Sky2CD window" in guide
    assert "CrimsonForge" in guide

    # Honest boundary language, not marketing claims.
    assert "does not guarantee fit" in guide or "No automatic body fitting" in guide
    assert "game-ready" in guide
    assert "THIRD_PARTY_NOTICES.md" in guide


def test_user_guide_scopes_nexus_download_to_gui_only():
    guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")

    assert "Nexus" in guide
    assert "not on Nexus" in guide or "not distributed on Nexus" in guide or "not offered as a Nexus download" in guide
    assert "GitHub releases only" in guide or "GitHub-only" in guide


def test_nexus_listing_guide_attaches_gui_only_and_keeps_boundary():
    listing = (ROOT / "docs" / "NEXUS_LISTING.md").read_text(encoding="utf-8")

    # Only the GUI exe should be described as the Nexus download.
    assert "Attach only `sky2cd-gui.exe`" in listing
    assert "Do not upload `sky2cd.exe`" in listing

    # Requirements stay honest: no Python needed, Blender/CrimsonForge separate.
    assert "No Python install required" in listing
    assert "Blender" in listing
    assert "CrimsonForge" in listing

    # No unsupported/marketing claims about automatic conversion.
    assert "does not automatically fit a body" in listing
    assert "never a" in listing
    assert "game-ready" in listing

    # README links to it and repeats the same GUI-only Nexus scoping.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/NEXUS_LISTING.md" in readme
    assert "only the" in readme.lower() and "sky2cd-gui.exe" in readme

