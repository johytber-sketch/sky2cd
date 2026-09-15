"""Unit tests for built-in body presets."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from sky2cd.meshir import MeshIR, load_meshir, save_meshir
from sky2cd.pipeline import convert
from sky2cd.presets import (
    get_default_preset_key,
    is_preset_key,
    list_presets,
    normalize_preset_key,
    resolve_body_config,
)
import numpy as np


def test_list_presets_returns_fem_kliff_and_vanilla():
    presets = list_presets()
    assert "fem_kliff" in presets
    assert "cd_vanilla_female" in presets
    assert "Fem Kliff" in presets["fem_kliff"]


def test_default_preset_key():
    assert get_default_preset_key() == "fem_kliff"


@pytest.mark.parametrize("name", ["fem_kliff", "fem-kliff", "FEM_KLIFF", "fem_kliff.json", "Preset: Skyrim Female -> Fem Kliff (Recommended)"])
def test_is_preset_key_positive(name: str):
    assert is_preset_key(name) is True
    assert normalize_preset_key(name) == "fem_kliff"


def test_is_preset_key_negative():
    assert is_preset_key("custom_body.json") is False
    assert is_preset_key("nonexistent_preset") is False


def test_resolve_body_config_for_builtin_preset():
    config = resolve_body_config("fem_kliff")
    assert "source_body" in config
    assert "target_body" in config
    assert Path(config["source_body"]).is_file()
    assert Path(config["target_body"]).is_file()

    # Load bodies to ensure valid MeshIR
    src_mesh = load_meshir(config["source_body"])
    tgt_mesh = load_meshir(config["target_body"])
    assert src_mesh.vertex_count > 0
    assert tgt_mesh.vertex_count > 0


def test_resolve_body_config_for_custom_file(tmp_path: Path):
    custom_cfg = tmp_path / "custom.json"
    custom_cfg.write_text(json.dumps({
        "source_body": "skyrim_female_base.meshir.json",
        "target_body": "fem_kliff_base.meshir.json",
        "scale": 1.0,
    }), encoding="utf-8")

    resolved = resolve_body_config(custom_cfg)
    assert resolved["scale"] == 1.0
    assert str(tmp_path) in resolved["source_body"]


def test_resolve_body_config_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        resolve_body_config("nonexistent_path_to_config.json")


def test_pipeline_convert_using_builtin_preset(tmp_path: Path):
    mesh = MeshIR(
        positions=np.array([[0.0, 0.0, 100.0], [1.0, 0.0, 100.0], [0.0, 1.0, 100.0]], dtype=np.float32),
        normals=np.array([[0.0, 1.0, 0.0]] * 3, dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        bone_names=["Root"],
        bone_indices=np.zeros((3, 4), dtype=np.uint16),
        bone_weights=np.array([[1.0, 0.0, 0.0, 0.0]] * 3, dtype=np.float32),
        materials=[],
        name="test_preset_outfit",
    )
    mesh_path = save_meshir(mesh, tmp_path / "test_outfit.meshir.json")
    out_dir = tmp_path / "out_preset"

    result = convert(mesh_path, "fem_kliff", out_dir, deformer_name="idw")
    assert result.pac_path.is_file()
    assert result.report_path.is_file()
    assert result.report["geometry_mode"] == "rigid_preview"
    assert result.report["deformer"] == "none"
    assert result.report["mesh"]["status"] == "geometry-preview-only"
    assert result.report["mesh"]["collision_correction"] == "disabled"
    from sky2cd.importers.obj_importer import read_obj
    from sky2cd.exporters.obj_exporter import convert_skyrim_to_cd_axes
    loaded = read_obj(result.report["output_obj"])
    np.testing.assert_allclose(loaded.positions, convert_skyrim_to_cd_axes(mesh.positions) * .0142875, atol=6e-7)
    np.testing.assert_array_equal(loaded.triangles, mesh.triangles)


def test_pipeline_applies_output_scale_after_deformation(tmp_path: Path):
    """output_scale must rescale the final exported mesh (real-world units) without
    disturbing the outfit/body coordinate match used for deformation."""
    mesh = MeshIR(
        positions=np.array([[0.0, 0.0, 100.0], [1.0, 0.0, 100.0], [0.0, 1.0, 100.0]], dtype=np.float32),
        normals=np.array([[0.0, 1.0, 0.0]] * 3, dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        bone_names=["Root"],
        bone_indices=np.zeros((3, 4), dtype=np.uint16),
        bone_weights=np.array([[1.0, 0.0, 0.0, 0.0]] * 3, dtype=np.float32),
        materials=[],
        name="test_output_scale_outfit",
    )
    mesh_path = save_meshir(mesh, tmp_path / "test_outfit.meshir.json")

    resolved_default = resolve_body_config("fem_kliff")
    base_kwargs = {
        "geometry_mode": "rigid_preview",
        "source_body": resolved_default["source_body"],
        "target_body": resolved_default["target_body"],
        "min_clearance": resolved_default.get("min_clearance", 0.001),
        "skyrim_slots": resolved_default.get("skyrim_slots", []),
    }

    cfg_no_scale = tmp_path / "no_scale.json"
    cfg_no_scale.write_text(json.dumps({**base_kwargs, "output_scale": 1.0}), encoding="utf-8")
    result_default = convert(mesh_path, cfg_no_scale, tmp_path / "out_default", deformer_name="idw")
    after_default = result_default.report["mesh"]["after"]["size"]

    cfg_scale = tmp_path / "scaled.json"
    cfg_scale.write_text(json.dumps({**base_kwargs, "output_scale": 0.0142875}), encoding="utf-8")
    result_scaled = convert(mesh_path, cfg_scale, tmp_path / "out_scaled", deformer_name="idw")
    after_scaled = result_scaled.report["mesh"]["after"]["size"]

    for default_v, scaled_v in zip(after_default, after_scaled):
        assert scaled_v == pytest.approx(default_v * 0.0142875, abs=2e-4)


def _body_mesh(positions: np.ndarray, name: str) -> MeshIR:
    n = len(positions)
    return MeshIR(
        positions=positions.astype(np.float32),
        normals=np.tile(np.array([0.0, 1.0, 0.0], dtype=np.float32), (n, 1)),
        uvs=np.zeros((n, 2), dtype=np.float32),
        triangles=np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.uint32)
        if n == 4 else (np.array([[0, 1, 2]], dtype=np.uint32) if n >= 3 else None),
        bone_names=["Root"],
        bone_indices=np.zeros((n, 4), dtype=np.uint16),
        bone_weights=np.tile(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), (n, 1)),
        name=name,
    )


def test_build_custom_preset_writes_reusable_config(tmp_path: Path):
    from sky2cd.presets import build_custom_preset

    source = _body_mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]), "cbbe_base")
    target = _body_mesh(np.array([[0, 0, 0], [1.2, 0, 0], [0, 1.3, 0], [0, 0, 1]]), "cd_kliff_reshape")

    config_path = build_custom_preset(source, target, "my_custom", tmp_path / "presets", scale=1.0)
    assert config_path.is_file()

    resolved = resolve_body_config(config_path)
    assert Path(resolved["source_body"]).is_file()
    assert Path(resolved["target_body"]).is_file()

    src_mesh = load_meshir(resolved["source_body"])
    tgt_mesh = load_meshir(resolved["target_body"])
    assert src_mesh.vertex_count == tgt_mesh.vertex_count == 4


def test_build_custom_preset_reused_across_outfits(tmp_path: Path):
    """Once baked, the same preset applies automatically to any outfit sharing the source topology."""
    from sky2cd.presets import build_custom_preset

    source = _body_mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]), "cbbe_base")
    target = _body_mesh(np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 1]]), "cd_kliff_reshape")
    config_path = build_custom_preset(source, target, "reused_preset", tmp_path / "presets")

    for idx in range(2):
        outfit = MeshIR(
            positions=np.array([[0.1, 0.1, 0.0], [0.9, 0.1, 0.0], [0.1, 0.9, 0.0]], dtype=np.float32) + idx,
            normals=np.array([[0.0, 1.0, 0.0]] * 3, dtype=np.float32),
            uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
            triangles=np.array([[0, 1, 2]], dtype=np.uint32),
            bone_names=["Root"],
            bone_indices=np.zeros((3, 4), dtype=np.uint16),
            bone_weights=np.array([[1.0, 0.0, 0.0, 0.0]] * 3, dtype=np.float32),
            name=f"outfit_{idx}",
        )
        mesh_path = save_meshir(outfit, tmp_path / f"outfit_{idx}.meshir.json")
        result = convert(mesh_path, config_path, tmp_path / f"out_{idx}", deformer_name="idw")
        assert result.pac_path.is_file()


def test_build_custom_preset_rejects_mismatched_vertex_counts(tmp_path: Path):
    from sky2cd.presets import build_custom_preset

    source = _body_mesh(np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]), "cbbe_base")
    target = _body_mesh(np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]), "mismatched")

    with pytest.raises(ValueError, match="vertex count"):
        build_custom_preset(source, target, "bad_preset", tmp_path / "presets")


def test_bundled_proxy_cannot_be_used_as_custom_fit(tmp_path):
    cfg = resolve_body_config("fem_kliff")
    cfg["geometry_mode"] = "body_fit"
    source_path = cfg["source_body"]
    with pytest.raises(ValueError, match="degenerate"):
        convert(source_path, cfg, tmp_path / "refused")
    assert not list((tmp_path / "refused").glob("*.obj"))


@pytest.mark.parametrize("damage", ["planar", "nonfinite", "topology", "degenerate", "isolated"])
def test_build_custom_preset_rejects_unsuitable_references(tmp_path, fitting_config, damage):
    from sky2cd.presets import build_custom_preset
    cfg = resolve_body_config(fitting_config)
    source = load_meshir(cfg["source_body"])
    target = load_meshir(cfg["target_body"])
    if damage == "planar":
        target.positions[:, 2] = 0
    elif damage == "nonfinite":
        target.positions[0, 0] = np.nan
    elif damage == "topology":
        target.triangles = target.triangles[:, ::-1]
    elif damage == "isolated":
        source.triangles = source.triangles[:1]
        target.triangles = target.triangles[:1]
    else:
        source.triangles[0] = [0, 0, 1]
        target.triangles[0] = [0, 0, 1]
    with pytest.raises(ValueError):
        build_custom_preset(source, target, "bad", tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("factor", [0, -1, np.inf, np.nan])
def test_preview_rejects_invalid_unit_scales(tmp_path, fitting_config, factor):
    cfg = resolve_body_config(fitting_config)
    cfg.update(geometry_mode="rigid_preview", output_scale=factor)
    with pytest.raises(ValueError, match="output_scale must be finite and positive"):
        convert(cfg["source_body"], cfg, tmp_path / "invalid_scale")


def test_preview_rejects_invalid_triangle_indices(tmp_path):
    bad = MeshIR(positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]]),
                 triangles=np.array([[0, 1, 3]]))
    path = save_meshir(bad, tmp_path / "bad.meshir.json")
    with pytest.raises(ValueError, match="triangle index"):
        convert(path, {"geometry_mode": "rigid_preview"}, tmp_path / "out")
