import numpy as np

from sky2cd.meshir import MeshIR, load_meshir, save_meshir


def test_meshir_round_trip(tmp_path):
    mesh = MeshIR(
        positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32),
        normals=np.array([[0, 0, 1]] * 3, dtype=np.float32),
        uvs=np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        bone_names=["root"],
        bone_indices=np.zeros((3, 4), dtype=np.uint16),
        bone_weights=np.array([[1, 0, 0, 0]] * 3, dtype=np.float32),
        materials=[{"name": "mat"}],
        name="tri",
    )
    path = save_meshir(mesh, tmp_path / "tri.meshir.json")
    loaded = load_meshir(path)

    assert loaded.name == "tri"
    assert loaded.bone_names == ["root"]
    assert loaded.materials == [{"name": "mat"}]
    np.testing.assert_allclose(loaded.positions, mesh.positions)
    np.testing.assert_array_equal(loaded.triangles, mesh.triangles)
