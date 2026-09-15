from __future__ import annotations

import numpy as np

from sky2cd.meshir import MeshIR


def validate_body_pair(source: MeshIR, target: MeshIR) -> None:
    """Check numerical prerequisites, not provenance or anatomical correspondence."""
    if source.vertex_count != target.vertex_count:
        raise ValueError("Body references must have the same vertex count and vertex correspondence.")
    if not np.array_equal(source.triangles, target.triangles):
        raise ValueError("Body references must have identical triangle topology and vertex order.")
    for label, mesh in (("source", source), ("target", target)):
        p = mesh.positions.astype(np.float64)
        if len(p) < 4 or not np.isfinite(p).all():
            raise ValueError(f"The {label} body reference must contain finite 3D surface geometry.")
        if np.linalg.matrix_rank(p - p.mean(axis=0)) < 3:
            raise ValueError(f"The {label} body reference is planar, not a 3D body surface.")
        if not len(mesh.triangles) or mesh.triangles.max() >= len(p):
            raise ValueError(f"The {label} body reference has missing or invalid surface topology.")
        if len(np.unique(mesh.triangles)) != len(p):
            raise ValueError(f"The {label} body reference has vertices outside its surface topology.")
        t = p[mesh.triangles]
        cross = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        if np.any(np.linalg.norm(cross, axis=1) <= np.finfo(float).eps * np.ptp(p, axis=0).max() ** 2):
            raise ValueError(f"The {label} body reference contains degenerate surface triangles.")


def validate_collision_surface(body: MeshIR) -> None:
    """Require a closed, consistently oriented surface with usable vertex normals."""
    validate_body_pair(body, body)
    triangles = body.triangles.astype(np.int64)
    edges = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    _, inverse, counts = np.unique(np.sort(edges, axis=1), axis=0, return_inverse=True, return_counts=True)
    directions = np.where(edges[:, 0] < edges[:, 1], 1, -1)
    if np.any(counts != 2) or np.any(np.bincount(inverse, weights=directions) != 0):
        raise ValueError("Collision requires a closed, consistently oriented manifold body surface.")
    p = body.positions.astype(np.float64)
    t = (p - p.mean(axis=0))[triangles]
    if np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() <= 0:
        raise ValueError("Collision body surface must be outward oriented.")
    normals = body.normals.astype(np.float64)
    lengths = np.linalg.norm(normals, axis=1)
    if not np.isfinite(normals).all() or np.any(lengths < 1e-8):
        raise ValueError("Collision body surface requires finite, nonzero outward vertex normals.")
    face_normals = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    if np.any(np.einsum("ij,ij->i", face_normals, normals[triangles].sum(axis=1)) <= 0):
        raise ValueError("Collision body normals disagree with the oriented surface.")


def validate_no_collapsed_triangles(before: MeshIR, after: MeshIR) -> None:
    def double_areas(mesh):
        t = mesh.positions.astype(np.float64)[mesh.triangles]
        return np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)

    if not np.isfinite(after.positions).all():
        raise ValueError("Geometry operation produced non-finite positions.")
    old, new = double_areas(before), double_areas(after)
    if np.any((old > 0) & (new <= old * 1e-8)):
        raise ValueError("Geometry operation collapsed source triangles; refusing to export the result.")
