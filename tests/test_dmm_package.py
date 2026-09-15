"""Unit tests for DMM-compatible loose-file mod packaging.

Schema verified against real, currently-installed DMM mods on the user's
machine (not guessed from documentation): both a manually-authored
"game_relative" mod ("Rivenheim Armor Shortened") and a real
CrimsonForge-generated "mesh_loose_mod" package ("Proxima Shell Mesh Mod")
confirm the on-disk layout this module reproduces: files/<game-relative-path>
+ manifest.json (+ modinfo.json for the CrimsonForge-compatible dialect).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sky2cd.dmm_package import DmmAsset, build_dmm_package, validate_dmm_package_inputs


def test_build_dmm_package_writes_files_manifest_and_modinfo(tmp_path: Path):
    asset = DmmAsset(
        entry_path="character/cd_phw_00_lb_00_0182.pac",
        pac_bytes=b"FAKE_PAC_BYTES",
        package_group="0009",
        vertices=51767,
        faces=97734,
        submeshes=1,
        source_obj_path="Dress_merged.obj",
    )
    result = build_dmm_package(
        [asset],
        tmp_path,
        title="Sherwood Huntress Lowerbody",
        author="tester",
        version="1.0.0",
        game_build="v2.02.00",
    )

    assert result.mod_dir.is_dir()
    assert result.manifest_path.is_file()
    assert result.modinfo_path.is_file()

    installed_pac = result.mod_dir / "files" / "character" / "cd_phw_00_lb_00_0182.pac"
    assert installed_pac.is_file()
    assert installed_pac.read_bytes() == b"FAKE_PAC_BYTES"
    assert installed_pac in result.file_paths

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["kind"] == "mesh_loose_mod"
    assert manifest["schema_version"] == 1
    assert manifest["files_root"] == "files"
    assert manifest["asset_count"] == 1
    assert manifest["assets"][0]["entry_path"] == "character/cd_phw_00_lb_00_0182.pac"
    assert manifest["assets"][0]["package_group"] == "0009"
    assert manifest["assets"][0]["vertices"] == 51767

    modinfo = json.loads(result.modinfo_path.read_text(encoding="utf-8"))
    assert modinfo["type"] == "mesh_loose_mod"
    assert modinfo["title"] == "Sherwood Huntress Lowerbody"


def test_build_dmm_package_multiple_assets_and_extra_files(tmp_path: Path):
    assets = [
        DmmAsset(entry_path="character/cd_phw_00_lb_00_0182.pac", pac_bytes=b"LB"),
        DmmAsset(entry_path="character/cd_phw_00_ub_00_0182.pac", pac_bytes=b"UB"),
    ]
    result = build_dmm_package(
        assets,
        tmp_path,
        title="Two Piece Set",
        extra_files={"character/cd_phw_00_lb_00_0182.pac_xml": b"<xml/>"},
    )

    assert (result.mod_dir / "files" / "character" / "cd_phw_00_lb_00_0182.pac").is_file()
    assert (result.mod_dir / "files" / "character" / "cd_phw_00_ub_00_0182.pac").is_file()
    assert (result.mod_dir / "files" / "character" / "cd_phw_00_lb_00_0182.pac_xml").read_bytes() == b"<xml/>"

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["asset_count"] == 2
    assert manifest["file_count"] == 3


def test_build_dmm_package_sanitizes_title_to_folder_name(tmp_path: Path):
    asset = DmmAsset(entry_path="character/cd_phw_00_lb_00_0182.pac", pac_bytes=b"X")
    result = build_dmm_package([asset], tmp_path, title="My Mod: Cool/Armor?")
    assert result.mod_dir.parent == tmp_path
    assert result.mod_dir.name  # non-empty, filesystem-safe
    assert "/" not in result.mod_dir.name
    assert ":" not in result.mod_dir.name
    assert "?" not in result.mod_dir.name


def test_build_dmm_package_rejects_empty_assets(tmp_path: Path):
    with pytest.raises(ValueError, match="empty"):
        build_dmm_package([], tmp_path, title="Empty")


@pytest.mark.parametrize(
    "bad_path",
    [
        "character\\cd_phw_00_lb_00_0182.pac",
        "/character/cd_phw_00_lb_00_0182.pac",
        "C:/character/cd_phw_00_lb_00_0182.pac",
        "../character/cd_phw_00_lb_00_0182.pac",
        "character/../../outside.pac",
    ],
)
def test_build_dmm_package_rejects_unsafe_entry_paths(tmp_path: Path, bad_path: str):
    asset = DmmAsset(entry_path=bad_path, pac_bytes=b"X")
    with pytest.raises(ValueError):
        build_dmm_package([asset], tmp_path, title="Bad Path Mod")


def test_build_dmm_package_rejects_unsafe_extra_file_paths(tmp_path: Path):
    asset = DmmAsset(entry_path="character/ok.pac", pac_bytes=b"X")
    with pytest.raises(ValueError):
        build_dmm_package(
            [asset],
            tmp_path,
            title="Bad Extra File Mod",
            extra_files={"../escape.pac_xml": b"<xml/>"},
        )


def test_validate_dmm_package_inputs_flags_missing_sidecar():
    asset = DmmAsset(entry_path="character/cd_phw_00_lb_00_0182.pac", pac_bytes=b"REBUILT_PAC")
    report = validate_dmm_package_inputs([asset], extra_files=None)

    assert report.ok is False
    assert len(report.issues) == 1
    assert "cd_phw_00_lb_00_0182.pac_xml" in report.issues[0].problem
    # provenance is still computed even though validation failed
    assert report.sha256_by_path["character/cd_phw_00_lb_00_0182.pac"] == hashlib.sha256(b"REBUILT_PAC").hexdigest()


def test_validate_dmm_package_inputs_passes_with_sidecar_present():
    asset = DmmAsset(entry_path="character/cd_phw_00_lb_00_0182.pac", pac_bytes=b"REBUILT_PAC")
    extra_files = {"character/cd_phw_00_lb_00_0182.pac_xml": b"<xml/>"}
    report = validate_dmm_package_inputs([asset], extra_files=extra_files)

    assert report.ok is True
    assert report.issues == []
    assert set(report.sha256_by_path) == {
        "character/cd_phw_00_lb_00_0182.pac",
        "character/cd_phw_00_lb_00_0182.pac_xml",
    }


def test_validate_dmm_package_inputs_uses_crimsonforge_parser_when_given():
    asset = DmmAsset(entry_path="character/cd_phw_00_lb_00_0182.pac", pac_bytes=b"TRUNCATED")
    extra_files = {"character/cd_phw_00_lb_00_0182.pac_xml": b"<xml/>"}

    class _FakeMeshParser:
        def parse_mesh(self, pac_bytes, filename=""):
            raise ValueError("not a valid PAC container")

    class _FakeCf:
        mesh_parser = _FakeMeshParser()

    report = validate_dmm_package_inputs([asset], extra_files=extra_files, cf=_FakeCf())

    assert report.ok is False
    assert "could not parse" in report.issues[0].problem


def test_build_dmm_package_strict_writes_provenance_on_success(tmp_path: Path):
    asset = DmmAsset(entry_path="character/cd_phw_00_lb_00_0182.pac", pac_bytes=b"REBUILT_PAC")
    extra_files = {"character/cd_phw_00_lb_00_0182.pac_xml": b"<xml/>"}

    result = build_dmm_package(
        [asset],
        tmp_path,
        title="Strict Mod",
        extra_files=extra_files,
        strict=True,
    )

    assert result.provenance_path is not None
    assert result.provenance_path.is_file()
    provenance = json.loads(result.provenance_path.read_text(encoding="utf-8"))
    assert provenance["strict_validation"] is True
    assert provenance["validation"]["ok"] is True
    assert provenance["validation"]["sha256_by_path"]["character/cd_phw_00_lb_00_0182.pac"] == hashlib.sha256(
        b"REBUILT_PAC"
    ).hexdigest()


def test_build_dmm_package_strict_rejects_missing_sidecar_and_writes_nothing(tmp_path: Path):
    asset = DmmAsset(entry_path="character/cd_phw_00_lb_00_0182.pac", pac_bytes=b"REBUILT_PAC")

    with pytest.raises(ValueError, match="missing required sidecar"):
        build_dmm_package([asset], tmp_path, title="Strict Reject Mod", strict=True)

    # nothing should have been written to disk on a rejected strict build
    assert not any(tmp_path.iterdir())


def test_build_dmm_package_non_strict_default_has_no_provenance(tmp_path: Path):
    asset = DmmAsset(entry_path="character/cd_phw_00_lb_00_0182.pac", pac_bytes=b"REBUILT_PAC")
    result = build_dmm_package([asset], tmp_path, title="Default Mod")

    assert result.provenance_path is None
    assert not (result.mod_dir / "provenance.json").exists()
