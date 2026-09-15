import numpy as np

from sky2cd.exporters.obj_exporter import write_obj
from sky2cd.importers.obj_importer import read_obj
from sky2cd.meshir import MeshIR


def _single_submesh_mesh() -> MeshIR:
    return MeshIR(
        name="single_test",
        positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=np.float32),
        normals=np.tile(np.array([0, 0, 1], dtype=np.float32), (4, 1)),
        uvs=np.array([[0, 0], [1, 0], [0, 1], [1, 1]], dtype=np.float32),
        triangles=np.array([[0, 1, 2], [1, 3, 2]], dtype=np.uint32),
    )


def _multi_submesh_mesh() -> MeshIR:
    return MeshIR(
        name="multi_test",
        positions=np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [2, 0, 0], [2, 1, 0]],
            dtype=np.float32,
        ),
        normals=np.tile(np.array([0, 0, 1], dtype=np.float32), (6, 1)),
        uvs=np.zeros((6, 2), dtype=np.float32),
        triangles=np.array([[0, 1, 2], [1, 3, 2], [1, 4, 5]], dtype=np.uint32),
        submesh_ids=np.array([0, 0, 1], dtype=np.int32),
    )


def test_read_obj_round_trips_single_submesh_mesh(tmp_path):
    mesh = _single_submesh_mesh()
    obj_path = write_obj(mesh, tmp_path / "single.obj", axis_convert=False)

    loaded = read_obj(obj_path)

    assert loaded.submesh_ids is None
    assert loaded.vertex_count == mesh.vertex_count
    assert loaded.triangles.shape[0] == mesh.triangles.shape[0]
    np.testing.assert_allclose(loaded.positions, mesh.positions, atol=1e-5)
    np.testing.assert_allclose(loaded.uvs, mesh.uvs, atol=1e-6)
    np.testing.assert_allclose(loaded.normals, mesh.normals, atol=1e-6)


def test_axis_normal_uv_roundtrip_rotates_only_at_skyrim_boundary(tmp_path):
    from sky2cd.exporters.obj_exporter import convert_skyrim_to_cd_axes
    mesh = _single_submesh_mesh()
    mesh.positions[:, 2] = [2, 3, 4, 5]
    mesh.uvs[:] = [.2, .3]
    first = read_obj(write_obj(mesh, tmp_path / "first.obj"))
    second = read_obj(write_obj(first, tmp_path / "second.obj", axis_convert=False))
    np.testing.assert_allclose(second.positions, convert_skyrim_to_cd_axes(mesh.positions), atol=1e-6)
    np.testing.assert_allclose(second.normals, convert_skyrim_to_cd_axes(mesh.normals), atol=1e-6)
    np.testing.assert_allclose(second.uvs, mesh.uvs, atol=1e-6)
    np.testing.assert_array_equal(second.triangles, mesh.triangles)


def test_read_obj_round_trips_multi_submesh_mesh(tmp_path):
    mesh = _multi_submesh_mesh()
    obj_path = write_obj(mesh, tmp_path / "multi.obj", axis_convert=False)

    loaded = read_obj(obj_path)

    assert loaded.submesh_ids is not None
    assert loaded.triangles.shape[0] == 3
    # Two triangles were tagged submesh 0, one was submesh 1 in the source mesh.
    assert list(loaded.submesh_ids) == [0, 0, 1]


def test_read_obj_detects_submeshes_delimited_by_o_lines_with_shared_material(tmp_path):
    # Real, live-confirmed bug: CrimsonForge's own donor OBJ exporter writes
    # one `o <name>` line per submesh but sometimes reuses the exact same
    # `usemtl` name across all of them (observed on a real 3-submesh dress
    # PAC donor) -- a usemtl-only boundary check silently collapsed all 3
    # submeshes into one, discarding the donor's original submesh/material
    # split once merged and re-exported. Submesh boundaries must also be
    # detected from `o` line changes, not just `usemtl` changes.
    obj_path = tmp_path / "cd_style_donor.obj"
    obj_path.write_text(
        "o Group_A\n"
        "usemtl SharedMat\n"
        "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "f 1 2 3\n"
        "o Group_B\n"
        "usemtl SharedMat\n"
        "v 0 0 1\nv 1 0 1\nv 0 1 1\n"
        "f 4 5 6\n"
        "o Group_C\n"
        "usemtl SharedMat\n"
        "v 0 0 2\nv 1 0 2\nv 0 1 2\n"
        "f 7 8 9\n",
        encoding="utf-8",
    )

    loaded = read_obj(obj_path)

    assert loaded.submesh_ids is not None
    assert loaded.triangles.shape[0] == 3
    # Each face's submesh id must differ from the others (3 distinct groups),
    # since each face belongs to a distinct `o` group despite sharing one material.
    assert len(set(loaded.submesh_ids.tolist())) == 3


def test_read_obj_missing_file_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        read_obj(tmp_path / "does_not_exist.obj")


def test_read_obj_rejects_non_triangulated_faces(tmp_path):
    import pytest

    bad_obj = tmp_path / "quad.obj"
    bad_obj.write_text(
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="triangulated"):
        read_obj(bad_obj)


def test_read_obj_assigns_name_from_stem_or_override(tmp_path):
    mesh = _single_submesh_mesh()
    obj_path = write_obj(mesh, tmp_path / "named_mesh.obj", axis_convert=False)

    loaded_default = read_obj(obj_path)
    assert loaded_default.name == "named_mesh"

    loaded_override = read_obj(obj_path, name="custom_name")
    assert loaded_override.name == "custom_name"
