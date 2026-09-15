"""Tests for .zip and .7z archive extraction and mesh discovery."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import py7zr
import pytest

from sky2cd.archive import discover_meshes, extract_archive, is_archive
from sky2cd.meshir import MeshIR, save_meshir
from sky2cd.pipeline import convert, pretty_report
import numpy as np


def _create_synthetic_mesh_json(path: Path, name: str = "outfit_part", materials: list | None = None) -> Path:
    mesh = MeshIR(
        positions=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
        normals=np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]], dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        bone_names=["Root"],
        bone_indices=np.zeros((3, 4), dtype=np.uint16),
        bone_weights=np.array([[1.0, 0.0, 0.0, 0.0]] * 3, dtype=np.float32),
        materials=materials or [],
        name=name,
    )
    return save_meshir(mesh, path)


def test_is_archive():
    assert is_archive("mod.zip") is True
    assert is_archive("mod.7z") is True
    assert is_archive("MOD.7Z") is True
    assert is_archive("mesh.nif") is False
    assert is_archive("mesh.meshir.json") is False


def test_extract_and_discover_zip(tmp_path: Path):
    zip_path = tmp_path / "mod.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("meshes/armor/cuirass_0.nif", "dummy nif 0")
        zf.writestr("meshes/armor/cuirass_1.nif", "dummy nif 1")
        zf.writestr("meshes/armor/boots.nif", "dummy boots")
        zf.writestr("textures/diffuse.dds", "dummy dds")

    dest = tmp_path / "extracted_zip"
    extracted = extract_archive(zip_path, dest)
    assert len(extracted) == 4

    meshes = discover_meshes(dest, prefer_high_weight=True)
    names = [p.name for p in meshes]
    # cuirass_1.nif should be preferred over cuirass_0.nif; boots.nif should also be found
    assert "cuirass_1.nif" in names
    assert "cuirass_0.nif" not in names
    assert "boots.nif" in names
    assert "diffuse.dds" not in names


def test_discover_meshes_excludes_bodyslide_shapedata_and_gnd_copies(tmp_path: Path):
    """Real Skyrim mods (e.g. BodySlide-built armor) ship BodySlide's own
    ShapeData reference-shape .nif and a low-detail GND ("on the ground"
    pickup) .nif alongside the real equipped _0/_1 mesh pair. Only the
    equipped mesh should be discovered as a convertible outfit piece."""
    mod_name = "[ELLE] Sherwood Huntress"
    equipped_dir = tmp_path / "meshes" / "Armor" / mod_name
    equipped_dir.mkdir(parents=True)
    (equipped_dir / "Dress_0.nif").write_text("dress0", encoding="utf-8")
    (equipped_dir / "Dress_1.nif").write_text("dress1", encoding="utf-8")

    gnd_dir = equipped_dir / "GND"
    gnd_dir.mkdir()
    (gnd_dir / "DRESS.nif").write_text("dress-pickup", encoding="utf-8")

    shapedata_dir = tmp_path / "CalienteTools" / "BodySlide" / "ShapeData" / mod_name
    shapedata_dir.mkdir(parents=True)
    (shapedata_dir / f"{mod_name} Dress.nif").write_text("dress-bodyslide-ref", encoding="utf-8")

    meshes = discover_meshes(tmp_path, prefer_high_weight=True)
    assert len(meshes) == 1
    assert meshes[0].name == "Dress_1.nif"
    assert meshes[0].parent == equipped_dir


def test_extract_and_discover_7z(tmp_path: Path):
    temp_dir = tmp_path / "to_pack_7z"
    temp_dir.mkdir()
    (temp_dir / "gloves_0.nif").write_text("g0", encoding="utf-8")
    (temp_dir / "gloves_1.nif").write_text("g1", encoding="utf-8")
    (temp_dir / "helmet.nif").write_text("h", encoding="utf-8")

    sz_path = tmp_path / "mod.7z"
    with py7zr.SevenZipFile(sz_path, "w") as sz:
        sz.writeall(temp_dir, arcname="meshes")

    dest = tmp_path / "extracted_7z"
    extracted = extract_archive(sz_path, dest)
    assert len(extracted) >= 3

    meshes = discover_meshes(dest, prefer_high_weight=True)
    names = [p.name for p in meshes]
    assert "gloves_1.nif" in names
    assert "gloves_0.nif" not in names
    assert "helmet.nif" in names


def test_archive_pipeline_conversion_round_trip(tmp_path: Path, fitting_config):
    # Setup body config and bodies
    from sky2cd.presets import resolve_body_config
    refs = resolve_body_config(fitting_config)
    source_body, target_body = refs["source_body"], refs["target_body"]
    body_config = tmp_path / "body_config.json"
    body_config.write_text(
        json.dumps({
            "source_body": str(source_body),
            "target_body": str(target_body),
            "skyrim_slots": ["32", "34"],
            "scale": 1.0,
            "min_clearance": 0.001,
        }),
        encoding="utf-8",
    )

    # Create outfit meshes in an archive
    pack_dir = tmp_path / "pack_mesh"
    _create_synthetic_mesh_json(pack_dir / "cuirass.meshir.json", "cuirass")
    _create_synthetic_mesh_json(pack_dir / "boots.meshir.json", "boots")

    sz_path = tmp_path / "outfit.7z"
    with py7zr.SevenZipFile(sz_path, "w") as sz:
        sz.writeall(pack_dir, arcname="meshes")

    out_dir = tmp_path / "out_archive"
    result = convert(sz_path, body_config, out_dir, deformer_name="idw")

    assert result.report_path.is_file()
    assert (out_dir / "meshes" / "cuirass.pac").is_file()
    assert (out_dir / "meshes" / "boots.pac").is_file()
    assert "meshes" in result.report
    assert len(result.report["meshes"]) == 2

    report_text = pretty_report(result.report_path)
    assert "outfit.7z" in report_text
    assert "2 meshes converted" in report_text


def test_archive_multiple_outfits_subfolder_preservation(tmp_path: Path, fitting_config):
    from sky2cd.presets import resolve_body_config
    refs = resolve_body_config(fitting_config)
    source_body, target_body = refs["source_body"], refs["target_body"]
    body_config = tmp_path / "body_config.json"
    body_config.write_text(
        json.dumps({
            "source_body": str(source_body),
            "target_body": str(target_body),
            "skyrim_slots": ["32"],
            "scale": 1.0,
            "min_clearance": 0.001,
        }),
        encoding="utf-8",
    )

    pack_dir = tmp_path / "pack_sets"
    _create_synthetic_mesh_json(pack_dir / "setA" / "boots.meshir.json", "boots_a")
    _create_synthetic_mesh_json(pack_dir / "setB" / "boots.meshir.json", "boots_b")

    sz_path = tmp_path / "sets.zip"
    with zipfile.ZipFile(sz_path, "w") as zf:
        zf.write(pack_dir / "setA" / "boots.meshir.json", arcname="setA/boots.meshir.json")
        zf.write(pack_dir / "setA" / "boots.meshir.npz", arcname="setA/boots.meshir.npz")
        zf.write(pack_dir / "setB" / "boots.meshir.json", arcname="setB/boots.meshir.json")
        zf.write(pack_dir / "setB" / "boots.meshir.npz", arcname="setB/boots.meshir.npz")

    out_dir = tmp_path / "out_sets"
    result = convert(sz_path, body_config, out_dir, deformer_name="idw")

    assert (out_dir / "setA" / "boots.pac").is_file()
    assert (out_dir / "setB" / "boots.pac").is_file()
    assert len(result.report["meshes"]) == 2


def test_archive_texture_extraction_bundles_dds_next_to_obj(tmp_path: Path, fitting_config):
    from sky2cd.presets import resolve_body_config
    refs = resolve_body_config(fitting_config)
    source_body, target_body = refs["source_body"], refs["target_body"]
    body_config = tmp_path / "body_config.json"
    body_config.write_text(
        json.dumps({
            "source_body": str(source_body),
            "target_body": str(target_body),
            "skyrim_slots": ["32"],
            "scale": 1.0,
            "min_clearance": 0.001,
        }),
        encoding="utf-8",
    )

    pack_dir = tmp_path / "pack_textured"
    _create_synthetic_mesh_json(
        pack_dir / "meshes" / "armor" / "cuirass.meshir.json",
        "cuirass",
        materials=[{
            "shape": "Armor:0",
            "diffuse_texture": r"textures\armor\cuirass_d.dds",
            "normal_texture": r"textures\armor\cuirass_n.dds",
        }],
    )
    textures_dir = pack_dir / "textures" / "armor"
    textures_dir.mkdir(parents=True)
    (textures_dir / "cuirass_d.dds").write_bytes(b"fake diffuse dds bytes")
    (textures_dir / "cuirass_n.dds").write_bytes(b"fake normal dds bytes")

    sz_path = tmp_path / "textured_outfit.zip"
    with zipfile.ZipFile(sz_path, "w") as zf:
        for f in pack_dir.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=str(f.relative_to(pack_dir)))

    out_dir = tmp_path / "out_textured"
    result = convert(sz_path, body_config, out_dir, deformer_name="idw")

    obj_path = Path(result.report["meshes"][0]["obj_path"])
    mtl_path = obj_path.with_suffix(".mtl")
    mtl_text = mtl_path.read_text(encoding="utf-8")
    assert "map_Kd textures/cuirass_d.dds" in mtl_text
    assert "map_Bump textures/cuirass_n.dds" in mtl_text

    copied_diffuse = obj_path.parent / "textures" / "cuirass_d.dds"
    copied_normal = obj_path.parent / "textures" / "cuirass_n.dds"
    assert copied_diffuse.is_file()
    assert copied_normal.is_file()
    assert copied_diffuse.read_bytes() == b"fake diffuse dds bytes"
    assert result.report["meshes"][0]["textures"]
