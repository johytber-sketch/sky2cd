import numpy as np
import pytest

from sky2cd.donor_merge import merge_onto_donor
from sky2cd.meshir import MeshIR


def _donor_two_submeshes() -> MeshIR:
    # Two separate quads (4 triangles total via triangulation), far apart in
    # space, tagged as two distinct submeshes.
    positions = np.array(
        [
            [0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0],       # group A quad
            [100, 0, 0], [101, 0, 0], [100, 1, 0], [101, 1, 0],  # group B quad
        ],
        dtype=np.float32,
    )
    triangles = np.array(
        [[0, 1, 2], [1, 3, 2], [4, 5, 6], [5, 7, 6]],
        dtype=np.uint32,
    )
    submesh_ids = np.array([0, 0, 1, 1], dtype=np.int32)
    return MeshIR(positions=positions, triangles=triangles, submesh_ids=submesh_ids, name="donor")


def _outfit_near(offset: tuple[float, float, float]) -> MeshIR:
    base = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32) + np.array(offset, dtype=np.float32)
    return MeshIR(
        positions=base,
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        name="outfit",
    )


def test_merge_shrinks_donor_geometry_toward_its_center():
    donor = _donor_two_submeshes()
    outfit = _outfit_near((0, 0, 0))

    merged = merge_onto_donor(donor, outfit, shrink_factor=0.1)

    donor_vertex_count = donor.vertex_count
    merged_donor_positions = merged.positions[:donor_vertex_count]
    original_span = donor.positions.max(axis=0) - donor.positions.min(axis=0)
    shrunk_span = merged_donor_positions.max(axis=0) - merged_donor_positions.min(axis=0)
    # Shrunk span should be roughly shrink_factor times the original span.
    np.testing.assert_allclose(shrunk_span, original_span * 0.1, atol=1e-3)


def test_merge_preserves_total_vertex_and_triangle_counts():
    donor = _donor_two_submeshes()
    outfit = _outfit_near((0, 0, 0))

    merged = merge_onto_donor(donor, outfit)

    assert merged.vertex_count == donor.vertex_count + outfit.vertex_count
    assert merged.triangles.shape[0] == donor.triangles.shape[0] + outfit.triangles.shape[0]
    assert merged.submesh_ids is not None
    assert merged.submesh_ids.shape[0] == merged.triangles.shape[0]


def test_merge_nearest_strategy_assigns_outfit_to_closest_donor_submesh():
    donor = _donor_two_submeshes()
    outfit_near_a = _outfit_near((0.2, 0.2, 0))  # near group A (around origin)

    merged = merge_onto_donor(donor, outfit_near_a, submesh_strategy="nearest")

    outfit_submesh_id = merged.submesh_ids[-1]
    assert outfit_submesh_id == 0  # group A's id

    outfit_near_b = _outfit_near((100.2, 0.2, 0))  # near group B
    merged_b = merge_onto_donor(donor, outfit_near_b, submesh_strategy="nearest")
    assert merged_b.submesh_ids[-1] == 1  # group B's id

    # Total submesh count stays at 2 (donor's original count) either way.
    assert len(set(merged.submesh_ids.tolist())) == 2
    assert len(set(merged_b.submesh_ids.tolist())) == 2


def test_merge_append_strategy_creates_new_submesh():
    donor = _donor_two_submeshes()
    outfit = _outfit_near((0, 0, 0))

    merged = merge_onto_donor(donor, outfit, submesh_strategy="append")

    outfit_submesh_id = merged.submesh_ids[-1]
    assert outfit_submesh_id == 2  # new id after donor's 0 and 1
    assert len(set(merged.submesh_ids.tolist())) == 3


def test_merge_handles_donor_without_submesh_ids():
    donor = MeshIR(
        positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        name="single_submesh_donor",
    )
    outfit = _outfit_near((0.1, 0.1, 0))

    merged = merge_onto_donor(donor, outfit)

    assert merged.submesh_ids is not None
    assert set(merged.submesh_ids.tolist()) == {0}


def test_merge_rejects_invalid_shrink_factor():
    donor = _donor_two_submeshes()
    outfit = _outfit_near((0, 0, 0))
    with pytest.raises(ValueError, match="shrink_factor"):
        merge_onto_donor(donor, outfit, shrink_factor=1.5)
    with pytest.raises(ValueError, match="shrink_factor"):
        merge_onto_donor(donor, outfit, shrink_factor=0.0)


def test_merge_rejects_invalid_submesh_strategy():
    donor = _donor_two_submeshes()
    outfit = _outfit_near((0, 0, 0))
    with pytest.raises(ValueError, match="submesh_strategy"):
        merge_onto_donor(donor, outfit, submesh_strategy="bogus")


def test_merge_rejects_empty_meshes():
    donor = _donor_two_submeshes()
    outfit = _outfit_near((0, 0, 0))
    empty = MeshIR(positions=np.zeros((0, 3), dtype=np.float32))
    with pytest.raises(ValueError):
        merge_onto_donor(empty, outfit)
    with pytest.raises(ValueError):
        merge_onto_donor(donor, empty)
