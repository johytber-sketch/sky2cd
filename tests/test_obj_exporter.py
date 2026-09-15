import numpy as np

from sky2cd.exporters.obj_exporter import convert_skyrim_to_cd_axes, write_obj
from sky2cd.meshir import MeshIR


def _triangle_mesh() -> MeshIR:
    return MeshIR(
        name="test_outfit",
        positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32),
        normals=np.array([[0, 0, 1]] * 3, dtype=np.float32),
        uvs=np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        bone_indices=np.zeros((3, 4), dtype=np.uint16),
        bone_weights=np.array([[1, 0, 0, 0]] * 3, dtype=np.float32),
    )


def test_axis_conversion_is_right_handed_and_z_up_to_y_up():
    # X stays, Y -> -Z, Z (Skyrim up) -> Y (CD up).
    converted = convert_skyrim_to_cd_axes(np.array([[1.0, 2.0, 3.0]]))
    assert np.allclose(converted, [[1.0, 3.0, -2.0]])


def test_write_obj_creates_matching_mtl_and_expected_counts(tmp_path):
    mesh = _triangle_mesh()
    obj_path = write_obj(mesh, tmp_path / "outfit.obj")

    assert obj_path.exists()
    mtl_path = obj_path.with_suffix(".mtl")
    assert mtl_path.exists()

    text = obj_path.read_text(encoding="utf-8")
    assert text.count("\nv ") + (1 if text.startswith("v ") else 0) == 3 or text.count("v ") >= 3
    assert "vt " in text
    assert "vn " in text
    assert "f " in text
    assert f"mtllib {mtl_path.name}" in text
    assert "o test_outfit" in text


def test_write_obj_preserves_close_float32_positions(tmp_path):
    from sky2cd.importers.obj_importer import read_obj
    mesh = _triangle_mesh()
    mesh.positions = np.array([[.1, .2, .3], [.1000001, .2, .3], [.1, .2000001, .3]], dtype=np.float32)
    result = read_obj(write_obj(mesh, tmp_path / "close.obj", axis_convert=False))
    np.testing.assert_array_equal(result.positions, mesh.positions)
    assert len(np.unique(result.positions, axis=0)) == 3


def test_write_obj_groups_submesh_faces_in_first_seen_order_not_numeric_order(tmp_path):
    # Real, confirmed submesh-order requirement: CrimsonForge's own re-import
    # and sky2cd's own read_obj recover submesh boundaries from the order
    # `usemtl` groups appear in the file, not from numeric submesh id value.
    # Use ids that are NOT already ascending (5 appears before 2) to catch
    # any vectorized rewrite that accidentally sorts by id value instead of
    # first appearance.
    mesh = MeshIR(
        name="multi_submesh_outfit",
        positions=np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]],
            dtype=np.float32,
        ),
        normals=np.array([[0, 0, 1]] * 6, dtype=np.float32),
        uvs=np.array([[0, 0], [1, 0], [0, 1], [0, 0], [1, 0], [0, 1]], dtype=np.float32),
        triangles=np.array([[0, 1, 2], [3, 4, 5]], dtype=np.uint32),
        submesh_ids=np.array([5, 2], dtype=np.int32),
        bone_indices=np.zeros((6, 4), dtype=np.uint16),
        bone_weights=np.array([[1, 0, 0, 0]] * 6, dtype=np.float32),
    )
    obj_path = write_obj(mesh, tmp_path / "multi.obj")
    text = obj_path.read_text(encoding="utf-8")

    first_usemtl_index = text.index("usemtl multi_submesh_outfit_submesh5")
    second_usemtl_index = text.index("usemtl multi_submesh_outfit_submesh2")
    assert first_usemtl_index < second_usemtl_index
    assert "o multi_submesh_outfit_submesh5\nusemtl multi_submesh_outfit_submesh5" in text
    assert "o multi_submesh_outfit_submesh2\nusemtl multi_submesh_outfit_submesh2" in text

    mtl_text = obj_path.with_suffix(".mtl").read_text(encoding="utf-8")
    assert "multi_submesh_outfit_submesh5" in mtl_text
    assert "multi_submesh_outfit_submesh2" in mtl_text


def test_write_obj_flips_v_coordinate(tmp_path):
    mesh = _triangle_mesh()
    obj_path = write_obj(mesh, tmp_path / "outfit.obj", axis_convert=False)
    lines = obj_path.read_text(encoding="utf-8").splitlines()
    vt_lines = [line for line in lines if line.startswith("vt ")]
    # Input UVs were (0,0), (1,0), (0,1) -> V flipped to 1, 1, 0
    v_values = [float(line.split()[2]) for line in vt_lines]
    assert v_values == [1.0, 1.0, 0.0]


def test_write_obj_without_axis_convert_preserves_raw_positions(tmp_path):
    mesh = _triangle_mesh()
    obj_path = write_obj(mesh, tmp_path / "raw.obj", axis_convert=False)
    lines = obj_path.read_text(encoding="utf-8").splitlines()
    v_lines = [line for line in lines if line.startswith("v ")]
    assert len(v_lines) == 3
    first = [float(x) for x in v_lines[0].split()[1:]]
    assert first == [0.0, 0.0, 0.0]
    second = [float(x) for x in v_lines[1].split()[1:]]
    assert second == [1.0, 0.0, 0.0]


def test_write_obj_face_indices_are_one_based(tmp_path):
    mesh = _triangle_mesh()
    obj_path = write_obj(mesh, tmp_path / "faces.obj")
    lines = obj_path.read_text(encoding="utf-8").splitlines()
    face_lines = [line for line in lines if line.startswith("f ")]
    assert len(face_lines) == 1
    tokens = face_lines[0].split()[1:]
    indices = [int(tok.split("/")[0]) for tok in tokens]
    assert indices == [1, 2, 3]


def test_write_obj_writes_map_kd_for_single_submesh_material(tmp_path):
    mesh = _triangle_mesh()
    mesh = mesh.copy_with(materials=[{
        "shape": "Armor:0",
        "diffuse_texture": r"textures\armor\example.dds",
        "normal_texture": None,
    }])
    obj_path = write_obj(mesh, tmp_path / "textured.obj")
    mtl_text = obj_path.with_suffix(".mtl").read_text(encoding="utf-8")
    assert "map_Kd textures/example.dds" in mtl_text
    assert "map_Bump" not in mtl_text


def test_write_obj_writes_map_kd_and_map_bump_per_submesh(tmp_path):
    mesh = MeshIR(
        name="multi_submesh_outfit",
        positions=np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]],
            dtype=np.float32,
        ),
        normals=np.array([[0, 0, 1]] * 6, dtype=np.float32),
        uvs=np.array([[0, 0], [1, 0], [0, 1], [0, 0], [1, 0], [0, 1]], dtype=np.float32),
        triangles=np.array([[0, 1, 2], [3, 4, 5]], dtype=np.uint32),
        submesh_ids=np.array([0, 1], dtype=np.int32),
        bone_indices=np.zeros((6, 4), dtype=np.uint16),
        bone_weights=np.array([[1, 0, 0, 0]] * 6, dtype=np.float32),
        materials=[
            {"shape": "Armor:0", "diffuse_texture": r"textures\armor\example.dds", "normal_texture": None},
            {
                "shape": "Body:0",
                "diffuse_texture": r"textures\body\skin.dds",
                "normal_texture": r"textures\body\skin_msn.dds",
            },
        ],
    )
    obj_path = write_obj(mesh, tmp_path / "multi_textured.obj")
    mtl_text = obj_path.with_suffix(".mtl").read_text(encoding="utf-8")
    assert "newmtl multi_submesh_outfit_submesh0" in mtl_text
    assert "newmtl multi_submesh_outfit_submesh1" in mtl_text
    assert "map_Kd textures/example.dds" in mtl_text
    assert "map_Kd textures/skin.dds" in mtl_text
    assert "map_Bump textures/skin_msn.dds" in mtl_text
    assert "bump textures/skin_msn.dds" in mtl_text
