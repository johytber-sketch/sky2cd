import numpy as np

from sky2cd.meshir import MeshIR
from sky2cd.weights.sidecar import read_sidecar, reapply_weights, write_sidecar


def test_sidecar_write_read_and_reapply_nearest_fallback(tmp_path):
    original = MeshIR(
        positions=np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32),
        bone_names=["root", "arm"],
        bone_indices=np.array([[0, 1, 0, 0], [1, 0, 0, 0]], dtype=np.uint16),
        bone_weights=np.array([[0.75, 0.25, 0, 0], [1, 0, 0, 0]], dtype=np.float32),
    )
    sidecar_path = write_sidecar(original, tmp_path / "mesh.cfmeta.json")
    sidecar = read_sidecar(sidecar_path)
    assert sidecar.bone_names == ["root", "arm"]

    edited = MeshIR(
        positions=np.array([[1.02, 0, 0], [0.01, 0, 0], [1.1, 0, 0]], dtype=np.float32),
        bone_indices=np.zeros((3, 4), dtype=np.uint16),
        bone_weights=np.zeros((3, 4), dtype=np.float32),
    )
    restored = reapply_weights(original, edited, sidecar)
    np.testing.assert_array_equal(restored.bone_indices[0], original.bone_indices[1])
    np.testing.assert_array_equal(restored.bone_indices[1], original.bone_indices[0])
    np.testing.assert_array_equal(restored.bone_indices[2], original.bone_indices[1])
    np.testing.assert_allclose(restored.bone_weights.sum(axis=1), 1.0)


def test_reapply_weights_prefers_same_index_exact_match_over_a_closer_different_index_vertex():
    # Real, confirmed semantics the vectorized rewrite must preserve: the
    # "exact match" fast path only ever compares edited vertex i against
    # source vertex i (same index), never "the nearest source vertex
    # overall". Two source vertices sitting almost on top of each other at
    # DIFFERENT indices must not be confused with each other just because
    # one happens to be marginally closer in space.
    original = MeshIR(
        positions=np.array([[0.0, 0.0, 0.0], [0.00001, 0.0, 0.0]], dtype=np.float32),
        bone_names=["root", "arm"],
        bone_indices=np.array([[0, 0, 0, 0], [1, 0, 0, 0]], dtype=np.uint16),
        bone_weights=np.array([[1, 0, 0, 0], [1, 0, 0, 0]], dtype=np.float32),
    )
    # edited[0] sits AT original[0]'s exact position (same index 0) -- this
    # must resolve to original[1]'s neighbor bone_indices=[0,...], not
    # original[1]=[1,...] even though original[1] is only 0.00001 away.
    edited = MeshIR(
        positions=np.array([[0.0, 0.0, 0.0], [0.00001, 0.0, 0.0]], dtype=np.float32),
        bone_indices=np.zeros((2, 4), dtype=np.uint16),
        bone_weights=np.zeros((2, 4), dtype=np.float32),
    )
    restored = reapply_weights(original, edited)
    np.testing.assert_array_equal(restored.bone_indices[0], original.bone_indices[0])
    np.testing.assert_array_equal(restored.bone_indices[1], original.bone_indices[1])
