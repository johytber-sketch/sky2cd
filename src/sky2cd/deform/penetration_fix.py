from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from sky2cd.meshir import MeshIR
from sky2cd.deform.normals import recompute_normals
from sky2cd.deform.validation import validate_collision_surface, validate_no_collapsed_triangles


def fix_penetration(
    outfit: MeshIR, target_body: MeshIR, min_clearance: float = 1e-4, *,
    max_distance: float, tree: cKDTree | None = None,
) -> MeshIR:
    """Opt-in, bounded local tangent-plane clearance; NOT an inside/outside solver.

    Only samples within max_distance of a body vertex are eligible, and each
    normal displacement is capped at that distance. Deep intersections and
    sparse regions are deliberately left unresolved for surface-based fitting.
    The caller must choose a radius in the reference body's units.
    """
    if not np.isfinite(min_clearance) or not np.isfinite(max_distance) or not 0 <= min_clearance <= max_distance or max_distance <= 0:
        raise ValueError("Local clearance requires 0 <= min_clearance <= max_distance, with finite positive max_distance.")
    validate_collision_surface(target_body)
    if outfit.vertex_count == 0:
        return outfit.copy_with()
    if tree is None:
        tree = cKDTree(target_body.positions)
    elif not np.array_equal(tree.data, target_body.positions):
        raise ValueError("Collision tree does not match target body positions.")
    distances, nearest = tree.query(outfit.positions, k=1, workers=-1)
    nearest_positions = target_body.positions[nearest]
    normals = target_body.normals[nearest].astype(np.float32)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    safe_normals = np.divide(normals, np.maximum(lengths, 1e-8))
    signed = np.sum((outfit.positions - nearest_positions) * safe_normals, axis=1)
    fixed = outfit.positions.copy()
    local = (distances <= max_distance) & (signed < min_clearance)
    amount = np.minimum(min_clearance - signed[local], max_distance)
    fixed[local] += safe_normals[local] * amount[:, None]
    result = outfit.copy_with(positions=fixed)
    validate_no_collapsed_triangles(outfit, result)
    return recompute_normals(result) if local.any() else result
