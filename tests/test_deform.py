import numpy as np
import pytest

from sky2cd.deform.idw import IDWDeformer
from sky2cd.deform.penetration_fix import fix_penetration
from sky2cd.meshir import MeshIR


def test_idw_deforms_cube_corner_toward_sphere():
    source = MeshIR(positions=np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32))
    target = MeshIR(positions=np.array([[2, 0, 0], [0, 2, 0], [0, 0, 2]], dtype=np.float32))
    outfit = MeshIR(positions=np.array([[1, 0, 0], [0.5, 0.5, 0]], dtype=np.float32))

    result = IDWDeformer(neighbors=2).deform(source, target, outfit)

    np.testing.assert_allclose(result.positions[0], [2, 0, 0], atol=1e-6)
    assert result.positions[1, 0] > outfit.positions[1, 0]
    assert result.positions[1, 1] > outfit.positions[1, 1]


def _closed_body():
    from sky2cd.deform.normals import recompute_normals
    return recompute_normals(MeshIR(
        positions=np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0], [0, 0, -1]]),
        triangles=np.array([[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
                            [5, 2, 1], [5, 3, 2], [5, 4, 3], [5, 1, 4]]),
    ))


def test_local_clearance_preserves_tangential_coordinates_and_leaves_remote_vertices():
    body = _closed_body()
    outfit = MeshIR(positions=np.array([[.02, .03, .95], [-.04, .01, .95], [0, 0, -3], [0, 0, 0]]))
    fixed = fix_penetration(outfit, body, min_clearance=0.1, max_distance=.2)
    np.testing.assert_allclose(fixed.positions[:2, :2], outfit.positions[:2, :2])
    np.testing.assert_allclose(fixed.positions[:2, 2], 1.1, atol=1e-6)
    np.testing.assert_array_equal(fixed.positions[2:], outfit.positions[2:])
    assert np.linalg.norm(fixed.positions - outfit.positions, axis=1).max() <= .2
    assert len(np.unique(fixed.positions, axis=0)) == 4


def test_penetration_fix_accepts_a_precomputed_tree_and_gives_identical_result():
    # Real perf win: multi-piece archives reuse one target_body cKDTree
    # across pieces instead of rebuilding it per piece -- must produce the
    # exact same result as the tree being built internally.
    from scipy.spatial import cKDTree

    body = _closed_body()
    outfit = MeshIR(positions=np.array([[0, 0, .95], [0, 0, 3]], dtype=np.float32))

    without_tree = fix_penetration(outfit, body, min_clearance=0.1, max_distance=.2)
    with_tree = fix_penetration(outfit, body, min_clearance=0.1, max_distance=.2, tree=cKDTree(body.positions))

    np.testing.assert_allclose(with_tree.positions, without_tree.positions)


@pytest.mark.parametrize("damage", ["plane", "open", "normals", "inward"])
def test_local_clearance_rejects_unsuitable_surfaces(damage):
    body = _closed_body()
    if damage == "plane":
        body.positions[:, 2] = 0
    elif damage == "open":
        body.triangles = body.triangles[:-1]
    elif damage == "normals":
        body.normals[:] = [0, 1, 0]
    else:
        body.triangles = body.triangles[:, ::-1]
    with pytest.raises(ValueError):
        fix_penetration(MeshIR(positions=np.array([[0, 0, .9]])), body, max_distance=.2)


def test_local_clearance_rejects_collapsing_triangle_instead_of_exporting_it():
    outfit = MeshIR(positions=np.array([[.01, 0, .91], [.01, 0, .92], [.02, 0, .91]]),
                    triangles=np.array([[0, 1, 2]]))
    with pytest.raises(ValueError, match="collapsed"):
        fix_penetration(outfit, _closed_body(), .01, max_distance=.2)


def test_recomputed_normals_follow_deformed_surface():
    from sky2cd.deform.normals import recompute_normals
    mesh = MeshIR(positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 1]]),
                  triangles=np.array([[0, 1, 2]]), normals=np.tile([0, 0, 1], (3, 1)))
    result = recompute_normals(mesh)
    expected = np.array([0, -1, 1]) / np.sqrt(2)
    np.testing.assert_allclose(result.normals, np.tile(expected, (3, 1)), atol=1e-6)


def test_idw_deformer_reuses_cached_tree_across_multiple_deform_calls():
    # Real perf win: source_body's cKDTree is built once per IDWDeformer
    # instance and reused across every piece of a multi-piece archive run
    # (pipeline.convert reuses one deformer instance for all pieces) --
    # confirm the cache actually activates on a second call with the same
    # source_body, and still gives the correct (identical) result.
    source = MeshIR(positions=np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32))
    target = MeshIR(positions=np.array([[2, 0, 0], [0, 2, 0], [0, 0, 2]], dtype=np.float32))
    outfit = MeshIR(positions=np.array([[1, 0, 0], [0.5, 0.5, 0]], dtype=np.float32))

    deformer = IDWDeformer(neighbors=2)
    first = deformer.deform(source, target, outfit)
    assert len(deformer._tree_cache) == 1
    second = deformer.deform(source, target, outfit)
    assert len(deformer._tree_cache) == 1  # still just one cached tree, not rebuilt

    np.testing.assert_allclose(first.positions, second.positions)
