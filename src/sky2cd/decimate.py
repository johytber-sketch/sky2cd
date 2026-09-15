"""Vertex-budget fixes for the real PAC-format submesh vertex-count limit.

**Real, confirmed constraint** (hit live this session): CrimsonForge's own
`build_pac()` packs each submesh's vertex count into an unsigned 16-bit field
when doing a full rebuild, so **a submesh can have at most 65,535 vertices**
-- exceeding it raises `struct.error: 'H' format requires 0 <= number <=
65535` deep inside CrimsonForge's rebuild path. A converted Skyrim outfit
merged onto a donor can easily exceed this.

Two real fixes, applied in order (cheapest/safest first):

1. **Weld duplicate vertices** (`weld_duplicate_vertices`) -- lossless.
   Exporters (Skyrim's NIF exporter included) duplicate a vertex for every
   distinct combination of position/normal/UV a triangle needs (hard edges,
   UV seams). Many of those duplicates are byte-identical once the mesh has
   passed through `sky2cd`'s own pipeline (no per-triangle UV splitting is
   introduced by our deformers) -- welding only vertices whose position,
   normal, UV, *and* bone weights all match (within a small rounding
   tolerance) removes this redundancy with **no visible change**.

2. **Quadric-edge-collapse decimation** (`decimate_mesh`) -- lossy, used only
   if welding alone doesn't reach budget. Uses `fast_simplification`
   (prebuilt wheels, no C++ toolchain required) to reduce triangle/vertex
   count while preserving overall shape/silhouette. Each decimated vertex's
   normal/UV/bone weights are copied from its single nearest *original*
   vertex (by position) rather than interpolated -- the same
   nearest-original-vertex philosophy already used for donor bone-weight
   inheritance in `sky2cd.donor_merge`, chosen for simplicity/robustness
   over blending, at some cost to fidelity right at simplified edges.

   **Confirmed live**: `fast_simplification`'s quadric collapse can plateau
   at a real, topology-dependent vertex floor no matter how small a target
   or how high `agg` is set (a 51,767-vert donor left only a ~13k-vertex
   budget for a 68,874-vert outfit; quadric decimation got permanently
   stuck at ~54,345 verts). When that happens, `decimate_mesh` falls back to
   grid-based vertex clustering (`_cluster_decimate`) on whatever quadric
   decimation already achieved -- clustering has no such stopping point and
   is guaranteed to reach any target, at the cost of some extra visual
   smoothness loss versus pure quadric collapse. This only engages on the
   remaining excess after quadric decimation, so most of a mesh's reduction
   still gets the higher-quality quadric treatment.

Neither of these can raise a mesh above its original vertex count, and both
operate on a single, self-contained mesh (intended for use on a converted
outfit **before** it is merged onto a donor via
`sky2cd.donor_merge.merge_onto_donor`) -- they do not track or preserve
`submesh_ids` boundaries within the input, since the intended input is the
un-merged, still-single-submesh converted outfit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sky2cd.meshir import MeshIR

__all__ = ["weld_duplicate_vertices", "decimate_mesh", "DecimationResult"]


def weld_duplicate_vertices(mesh: MeshIR, decimals: int = 5) -> MeshIR:
    """Losslessly merge vertices with identical position+normal+UV+bone data.

    Only vertices whose *entire* attribute set matches (within `decimals`
    decimal places, to absorb float round-trip noise) are merged, so this
    never touches real UV-seam or hard-edge vertices (which differ in
    normal/UV even at a shared position) -- it strictly removes exact,
    redundant duplication introduced by mesh export formats.
    """
    if mesh.vertex_count == 0 or mesh.triangles.shape[0] == 0:
        return mesh

    key = np.round(
        np.hstack(
            [
                mesh.positions.astype(np.float64),
                mesh.normals.astype(np.float64),
                mesh.uvs.astype(np.float64),
                mesh.bone_indices.astype(np.float64),
                mesh.bone_weights.astype(np.float64),
            ]
        ),
        decimals,
    )
    _, first_index, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)

    new_triangles = inverse[mesh.triangles.astype(np.int64)].astype(np.uint32)
    degenerate = (
        (new_triangles[:, 0] == new_triangles[:, 1])
        | (new_triangles[:, 1] == new_triangles[:, 2])
        | (new_triangles[:, 0] == new_triangles[:, 2])
    )
    kept_triangles = new_triangles[~degenerate]
    kept_submesh_ids = mesh.submesh_ids[~degenerate] if mesh.submesh_ids is not None else None

    return mesh.copy_with(
        positions=mesh.positions[first_index],
        normals=mesh.normals[first_index],
        uvs=mesh.uvs[first_index],
        bone_indices=mesh.bone_indices[first_index],
        bone_weights=mesh.bone_weights[first_index],
        triangles=kept_triangles,
        submesh_ids=kept_submesh_ids,
    )


@dataclass(frozen=True)
class DecimationResult:
    mesh: MeshIR
    original_vertex_count: int
    decimated_vertex_count: int
    cluster_fallback_used: bool = False


def _cluster_decimate(positions: np.ndarray, triangles: np.ndarray, target_vertex_count: int) -> tuple[np.ndarray, np.ndarray]:
    """Grid-based vertex clustering: reaches any `target_vertex_count >= 1`.

    **Confirmed live**: `fast_simplification`'s quadric edge-collapse can get
    permanently stuck well above a requested target on some real, multi-shell
    outfit meshes -- reducing `target_count` further and raising `agg` to its
    max of `10.0` produced the *exact same* result (54,345/54,353 verts) no
    matter how small a target was requested, even on a single isolated mesh
    island tested down to `target_count=10`. That's a real topology-dependent
    stopping point in that algorithm, not a tuning problem.

    Vertex clustering has no such stopping point: quantizing positions to a
    grid and merging every vertex that lands in the same cell always shrinks
    the vertex count as the grid gets coarser, all the way down to 1 vertex
    for a large enough cell -- so a plain bisection search over cell size is
    guaranteed to find one that lands at-or-under any target. This is a
    blunter, lower-quality reduction than quadric decimation (no attempt to
    preserve curvature/detail, just proximity merging), so it's used only as
    a last-resort fallback after quadric decimation has already done as much
    of the reduction as it topologically can.
    """
    bbox_min = positions.min(axis=0)
    bbox_max = positions.max(axis=0)
    diag = float(np.linalg.norm(bbox_max - bbox_min))
    if diag <= 0:
        raise ValueError("cannot cluster-decimate a mesh with a degenerate (zero-size) bounding box")

    def _cluster_indices(cell_size: float) -> np.ndarray:
        keys = np.floor((positions - bbox_min) / cell_size).astype(np.int64)
        return np.unique(keys, axis=0, return_inverse=True)[1].reshape(-1)

    lo, hi = diag * 1e-7, diag
    inverse = _cluster_indices(hi)
    for _ in range(60):
        mid = (lo + hi) / 2.0
        inv = _cluster_indices(mid)
        if int(inv.max()) + 1 > target_vertex_count:
            lo = mid
        else:
            hi = mid
            inverse = inv
        if hi - lo < diag * 1e-9:
            break

    n_clusters = int(inverse.max()) + 1
    cluster_positions = np.zeros((n_clusters, 3), dtype=np.float64)
    counts = np.zeros(n_clusters, dtype=np.int64)
    np.add.at(cluster_positions, inverse, positions)
    np.add.at(counts, inverse, 1)
    cluster_positions /= counts[:, None]

    new_triangles = inverse[triangles]
    degenerate = (
        (new_triangles[:, 0] == new_triangles[:, 1])
        | (new_triangles[:, 1] == new_triangles[:, 2])
        | (new_triangles[:, 0] == new_triangles[:, 2])
    )
    # Exact-duplicate-row removal only (not permutation-aware) so triangle
    # winding order -- and therefore backface culling -- is preserved for
    # every triangle that's kept.
    kept_triangles = np.unique(new_triangles[~degenerate], axis=0)
    return cluster_positions, kept_triangles


def decimate_mesh(mesh: MeshIR, target_vertex_count: int, *, agg: float = 7.0, max_iterations: int = 10) -> DecimationResult:
    """Reduce `mesh` to at most `target_vertex_count` vertices via decimation.

    Uses `fast_simplification.simplify()`, whose `target_count` parameter is
    a *triangle* count; this estimates the matching triangle target from the
    mesh's own current triangle/vertex ratio, then iteratively tightens it
    (up to `max_iterations` times) if the first pass doesn't reach the
    vertex budget. Each retry both shrinks the triangle target *and*
    escalates `agg` toward its real maximum of `10.0`.

    If quadric decimation still hasn't reached the target after
    `max_iterations` attempts (confirmed live: it can plateau at a real,
    topology-dependent floor regardless of target/`agg`), this falls back to
    `_cluster_decimate` on whatever quadric decimation already achieved, to
    guarantee the real PAC vertex budget is met -- see `_cluster_decimate`'s
    docstring for why that fallback always converges where quadric collapse
    sometimes can't.

    Each decimated vertex's normal/UV/bone weights are copied from its
    single nearest original vertex (by 3D position), not interpolated.

    Raises:
        ValueError: if `target_vertex_count` is too small to represent any
            triangle mesh (`< 4`).
    """
    if target_vertex_count < 4:
        raise ValueError(f"target_vertex_count must be >= 4, got {target_vertex_count}")
    if mesh.vertex_count <= target_vertex_count:
        return DecimationResult(
            mesh=mesh, original_vertex_count=mesh.vertex_count, decimated_vertex_count=mesh.vertex_count
        )
    if mesh.triangles.shape[0] == 0:
        raise ValueError("cannot decimate a mesh with no triangles")

    import fast_simplification as fs
    from scipy.spatial import cKDTree

    original_positions = mesh.positions.astype(np.float64)
    original_triangles = mesh.triangles.astype(np.int64)

    ratio = original_triangles.shape[0] / max(mesh.vertex_count, 1)
    target_triangle_count = max(4, int(target_vertex_count * ratio))

    dec_points = original_positions
    dec_triangles = original_triangles
    current_agg = agg
    for _ in range(max_iterations):
        dec_points, dec_triangles = fs.simplify(
            original_positions,
            original_triangles,
            target_count=target_triangle_count,
            agg=current_agg,
        )
        if dec_points.shape[0] <= target_vertex_count:
            break
        target_triangle_count = max(4, int(target_triangle_count * 0.8))
        current_agg = min(10.0, current_agg + 1.0)

    cluster_fallback_used = False
    if dec_points.shape[0] > target_vertex_count:
        # Real, confirmed limit: quadric decimation can plateau above target
        # regardless of target/agg (see `_cluster_decimate`'s docstring).
        # Finish the remaining reduction via grid clustering, which always
        # converges, applied to whatever quadric decimation already produced
        # so its shape-preserving work up to the plateau isn't wasted.
        dec_points, dec_triangles = _cluster_decimate(dec_points, dec_triangles, target_vertex_count)
        cluster_fallback_used = True

    nearest_original_idx = cKDTree(original_positions).query(dec_points)[1]

    new_mesh = mesh.copy_with(
        positions=dec_points.astype(np.float32),
        normals=mesh.normals[nearest_original_idx],
        uvs=mesh.uvs[nearest_original_idx],
        bone_indices=mesh.bone_indices[nearest_original_idx],
        bone_weights=mesh.bone_weights[nearest_original_idx],
        triangles=dec_triangles.astype(np.uint32),
        submesh_ids=None,
    )
    return DecimationResult(
        mesh=new_mesh,
        original_vertex_count=mesh.vertex_count,
        decimated_vertex_count=new_mesh.vertex_count,
        cluster_fallback_used=cluster_fallback_used,
    )
