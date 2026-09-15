import os
import sys
import types

import numpy as np
import pytest

from sky2cd.importers.nif_importer import import_nif


class FakeShape:
    name = "Armor:0"
    verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    normals = [(0, 0, 1), (0, 0, 1), (0, 0, 1)]
    uvs = [(0, 0), (1, 0), (0, 1)]
    tris = [(0, 1, 2)]
    bone_weights = {
        "NPC Spine": [(0, 0.25), (1, 0.5)],
        "NPC Pelvis": [(0, 0.75), (2, 1.0)],
    }
    textures = {"Diffuse": r"textures\armor\example.dds"}


class FakeNifFile:
    def __init__(self, path):
        self.path = path
        self.shapes = [FakeShape()]


class FakeShapeBody:
    name = "Body:0"
    verts = [(2, 0, 0), (3, 0, 0), (2, 1, 0), (3, 1, 0)]
    normals = [(0, 0, 1)] * 4
    uvs = [(0, 0), (1, 0), (0, 1), (1, 1)]
    tris = [(0, 1, 2), (1, 3, 2)]
    bone_weights = {"NPC Spine": [(0, 1.0), (1, 1.0), (2, 1.0), (3, 1.0)]}
    textures = {"Diffuse": r"textures\body\skin.dds", "Normal": r"textures\body\skin_msn.dds"}


class FakeMultiShapeNifFile:
    def __init__(self, path):
        self.path = path
        self.shapes = [FakeShape(), FakeShapeBody()]


class FakeShapeVirtualGround:
    """Simulates a BodySlide/Outfit Studio non-rendering helper shape."""

    name = "VirtualGround"
    verts = [(-80, -80, 0), (80, -80, 0), (-80, 80, 0), (80, 80, 0)]
    normals = [(0, 0, 1)] * 4
    uvs = [(0, 0), (1, 0), (0, 1), (1, 1)]
    tris = [(0, 1, 2), (1, 3, 2)]
    bone_weights = {}
    textures = {}


class FakeShapeVirtualCBBE:
    name = "VirtualCBBE"
    verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    normals = [(0, 0, 1)] * 3
    uvs = [(0, 0), (1, 0), (0, 1)]
    tris = [(0, 1, 2)]
    bone_weights = {}
    textures = {}


class FakeNifFileWithVirtualHelperShapes:
    def __init__(self, path):
        self.path = path
        self.shapes = [FakeShape(), FakeShapeVirtualCBBE(), FakeShapeVirtualGround(), FakeShapeBody()]


def test_import_nif_multi_shape_assigns_submesh_ids_and_materials(monkeypatch, tmp_path):
    fake_module = types.SimpleNamespace(NifFile=FakeMultiShapeNifFile)
    monkeypatch.setitem(sys.modules, "pynifly", fake_module)
    monkeypatch.delitem(sys.modules, "pyn", raising=False)
    nif_path = tmp_path / "outfit.nif"
    nif_path.write_bytes(b"synthetic placeholder; FakeMultiShapeNifFile supplies geometry")

    mesh = import_nif(nif_path)

    assert mesh.vertex_count == 3 + 4
    assert mesh.triangles.shape[0] == 1 + 2
    assert mesh.submesh_ids is not None
    # First shape's single triangle -> submesh 0, second shape's two triangles -> submesh 1.
    np.testing.assert_array_equal(mesh.submesh_ids, np.array([0, 1, 1], dtype=np.int32))

    assert len(mesh.materials) == 2
    assert mesh.materials[0]["shape"] == "Armor:0"
    assert mesh.materials[0]["diffuse_texture"] == r"textures\armor\example.dds"
    assert mesh.materials[0]["normal_texture"] is None
    assert mesh.materials[1]["shape"] == "Body:0"
    assert mesh.materials[1]["diffuse_texture"] == r"textures\body\skin.dds"
    assert mesh.materials[1]["normal_texture"] == r"textures\body\skin_msn.dds"

    # Triangle indices for the second shape must be offset by the first
    # shape's vertex count (standard shared-vertex-buffer concatenation).
    assert mesh.triangles[1:].min() >= 3


def test_import_nif_exact_exclusions_keep_material_indices_contiguous(monkeypatch, tmp_path):
    fake_module = types.SimpleNamespace(NifFile=FakeNifFileWithVirtualHelperShapes)
    monkeypatch.setitem(sys.modules, "pynifly", fake_module)
    monkeypatch.delitem(sys.modules, "pyn", raising=False)
    nif_path = tmp_path / "outfit.nif"
    nif_path.write_bytes(b"synthetic placeholder; FakeNifFileWithVirtualHelperShapes supplies geometry")

    with pytest.warns(UserWarning, match="Explicitly excluding"):
        mesh = import_nif(nif_path, exclude_shapes=("VirtualCBBE", "VirtualGround"))

    shape_names = [m["shape"] for m in mesh.materials]
    assert "VirtualCBBE" not in shape_names
    assert "VirtualGround" not in shape_names
    assert shape_names == ["Armor:0", "Body:0"]
    # Only the real armor (3 verts) and body (4 verts) shapes should remain.
    assert mesh.vertex_count == 3 + 4
    assert mesh.triangles.shape[0] == 1 + 2
    np.testing.assert_array_equal(mesh.submesh_ids, [0, 1, 1])
    from sky2cd.exporters.obj_exporter import write_obj
    obj = write_obj(mesh, tmp_path / "filtered.obj")
    assert "map_Kd textures/skin.dds" in obj.with_suffix(".mtl").read_text()


def test_import_nif_does_not_remove_shapes_by_name_alone(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pynifly", types.SimpleNamespace(NifFile=FakeNifFileWithVirtualHelperShapes))
    path = tmp_path / "all.nif"
    path.touch()
    with pytest.warns(UserWarning, match="Retaining possible helper"):
        mesh = import_nif(path)
    assert [m["shape"] for m in mesh.materials] == ["Armor:0", "VirtualCBBE", "VirtualGround", "Body:0"]
    np.testing.assert_array_equal(mesh.submesh_ids, [0, 1, 2, 2, 3, 3])


def test_empty_shape_does_not_leave_material_index_hole():
    from sky2cd.importers.nif_importer import _meshir_from_pynifly_nif
    empty = types.SimpleNamespace(name="empty", verts=[])
    mesh = _meshir_from_pynifly_nif(types.SimpleNamespace(shapes=[FakeShape(), empty, FakeShapeBody()]), "test")
    np.testing.assert_array_equal(mesh.submesh_ids, [0, 1, 1])


def test_import_nif_uses_pynifly_niffile_adapter(monkeypatch, tmp_path):
    fake_module = types.SimpleNamespace(NifFile=FakeNifFile)
    monkeypatch.setitem(sys.modules, "pynifly", fake_module)
    monkeypatch.delitem(sys.modules, "pyn", raising=False)
    nif_path = tmp_path / "armor.nif"
    nif_path.write_bytes(b"synthetic placeholder; FakeNifFile supplies geometry")

    mesh = import_nif(nif_path)

    assert mesh.name == "armor"
    assert mesh.materials[0]["shape"] == "Armor:0"
    assert mesh.materials[0]["diffuse_texture"] == r"textures\armor\example.dds"
    assert mesh.submesh_ids is None
    assert mesh.bone_names == ["NPC Spine", "NPC Pelvis"]
    np.testing.assert_allclose(mesh.positions, FakeShape.verts)
    np.testing.assert_allclose(mesh.normals, FakeShape.normals)
    np.testing.assert_allclose(mesh.uvs, FakeShape.uvs)
    np.testing.assert_array_equal(mesh.triangles, np.array([[0, 1, 2]], dtype=np.uint32))
    np.testing.assert_array_equal(mesh.bone_indices[0], [1, 0, 0, 0])
    np.testing.assert_allclose(mesh.bone_weights[0], [0.75, 0.25, 0, 0])


def test_import_nif_optional_real_pynifly_fixture():
    fixture = os.environ.get("PYNIFLY_TEST_NIF")
    if not fixture:
        pytest.skip("Set PYNIFLY_TEST_NIF to exercise real PyNifly against a real .nif fixture")

    mesh = import_nif(fixture)

    assert mesh.vertex_count > 0
    assert mesh.positions.shape == (mesh.vertex_count, 3)
    assert mesh.normals.shape == (mesh.vertex_count, 3)
    assert mesh.uvs.shape == (mesh.vertex_count, 2)
    assert mesh.triangles.shape[1] == 3
