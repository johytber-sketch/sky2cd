"""Tests for sky2cd.decimate (the real PAC vertex-limit fix: weld + decimate)."""

from __future__ import annotations

import numpy as np
import pytest

from sky2cd.decimate import DecimationResult, decimate_mesh, weld_duplicate_vertices
from sky2cd.meshir import MeshIR


def _grid_mesh(n: int) -> MeshIR:
    xs, ys = np.meshgrid(np.arange(n, dtype=np.float32), np.arange(n, dtype=np.float32))
    positions = np.stack([xs.ravel(), ys.ravel(), np.zeros(n * n, dtype=np.float32)], axis=1)
    triangles = []
    for row in range(n - 1):
        for col in range(n - 1):
            a = row * n + col
            b = row * n + col + 1
            c = (row + 1) * n + col
            d = (row + 1) * n + col + 1
            triangles.append([a, b, d])
            triangles.append([a, d, c])
    return MeshIR(positions=positions, triangles=np.array(triangles, dtype=np.uint32), name="grid")


def test_weld_duplicate_vertices_merges_exact_duplicates():
    # Two triangles sharing an edge, but exported with fully duplicated
    # vertices at the shared edge (identical position/normal/UV/weights) --
    # exactly the kind of redundancy real mesh exporters introduce.
    positions = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0],  # duplicate of vertex 0
            [1.0, 0.0, 0.0],  # duplicate of vertex 1
            [1.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    mesh = MeshIR(
        positions=positions,
        normals=np.array([[0.0, 0.0, 1.0]] * 6, dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0], [1.0, 0.0], [1.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2], [3, 4, 5]], dtype=np.uint32),
        name="dup_test",
    )

    welded = weld_duplicate_vertices(mesh)

    assert welded.vertex_count == 4
    assert welded.triangles.shape == (2, 3)
    # Both triangles should still reference valid, in-range vertex indices.
    assert welded.triangles.max() < welded.vertex_count


def test_weld_duplicate_vertices_keeps_distinct_uv_seam_vertices():
    # Same position, but different UV (a real UV-seam vertex) -- must NOT be welded.
    positions = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 0.0]], dtype=np.float32)
    mesh = MeshIR(
        positions=positions,
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.9, 0.9]], dtype=np.float32),
        triangles=np.array([[0, 1, 2], [3, 1, 2]], dtype=np.uint32),
        name="seam_test",
    )

    welded = weld_duplicate_vertices(mesh)

    assert welded.vertex_count == 4  # nothing merged: vertex 0 and 3 differ in UV


def test_weld_duplicate_vertices_no_op_when_no_duplicates():
    mesh = _grid_mesh(4)
    welded = weld_duplicate_vertices(mesh)
    assert welded.vertex_count == mesh.vertex_count
    assert welded.triangles.shape == mesh.triangles.shape


def test_decimate_mesh_is_no_op_when_already_under_target():
    mesh = _grid_mesh(4)
    result = decimate_mesh(mesh, target_vertex_count=1000)
    assert isinstance(result, DecimationResult)
    assert result.mesh.vertex_count == mesh.vertex_count
    assert result.decimated_vertex_count == mesh.vertex_count


def test_decimate_mesh_reduces_vertex_count_below_target():
    mesh = _grid_mesh(30)  # 900 vertices
    result = decimate_mesh(mesh, target_vertex_count=100, agg=7.0)

    assert result.original_vertex_count == 900
    assert result.decimated_vertex_count <= 100
    assert result.mesh.vertex_count == result.decimated_vertex_count
    assert result.mesh.triangles.max() < result.mesh.vertex_count
    # Attribute arrays must stay in sync with the new vertex count.
    assert result.mesh.normals.shape[0] == result.mesh.vertex_count
    assert result.mesh.uvs.shape[0] == result.mesh.vertex_count
    assert result.mesh.bone_weights.shape[0] == result.mesh.vertex_count


def test_decimate_mesh_rejects_tiny_target():
    mesh = _grid_mesh(4)
    with pytest.raises(ValueError):
        decimate_mesh(mesh, target_vertex_count=2)


def test_decimate_mesh_falls_back_to_cluster_decimation_when_quadric_plateaus(monkeypatch):
    # Force `fast_simplification.simplify` to always return a result stuck
    # above target, simulating the real, confirmed plateau (a real
    # multi-island outfit mesh got permanently stuck at ~54,345 verts no
    # matter the target/agg) without depending on being able to reliably
    # reproduce that plateau with a small synthetic mesh.
    mesh = _grid_mesh(30)  # 900 vertices

    import fast_simplification as fs

    def _stuck_simplify(points, triangles, target_count, agg):
        # Always return the same, unreduced-enough result regardless of target/agg.
        return points, triangles

    monkeypatch.setattr(fs, "simplify", _stuck_simplify)

    result = decimate_mesh(mesh, target_vertex_count=50, max_iterations=2)

    assert result.cluster_fallback_used is True
    assert result.decimated_vertex_count <= 50
    assert result.mesh.vertex_count == result.decimated_vertex_count
    assert result.mesh.triangles.max() < result.mesh.vertex_count
    assert result.mesh.normals.shape[0] == result.mesh.vertex_count
    assert result.mesh.uvs.shape[0] == result.mesh.vertex_count
    assert result.mesh.bone_weights.shape[0] == result.mesh.vertex_count
