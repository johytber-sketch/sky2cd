"""Experimental "no-Blender" donor-merge for the replacer workflow.

**Status: experimental and unverified against a real Crimson Desert install
or a real CrimsonForge install** -- neither is available in this
environment. See the README's "Experimental: merge without Blender"
section for the full caveat and the documented manual-Blender fallback.

## The idea

The remaining manual step in the sky2cd -> CrimsonForge replacer workflow
is normally done in Blender: hide the donor item's own geometry, splice in
the newly-converted outfit mesh, re-weight it to the donor's skeleton, and
reconcile submesh counts so textures still map correctly.

CrimsonForge's own mesh importer (``core/mesh_importer.py`` in that
project) is documented to fall back to **positional donor-vertex
matching** when no ``.cfmeta.json`` sidecar accompanies an imported mesh --
i.e. it can infer which bones/weights to bind new geometry to based on
proximity to the *original* donor vertices, without a human doing that
binding in Blender. Critically, that matching is done **within a single
submesh** (``_choose_pac_donor_indices`` in CrimsonForge only searches the
one donor submesh a new vertex was assigned to) -- so which submesh a new
vertex lands in is exactly as important as the position match itself: if a
vertex is assigned to the wrong submesh, it will inherit skin weights from
an unrelated part of the donor (e.g. a strap/collar/cape bound to a very
different bone), which can make it fly across the screen once the
skeleton animates, even though its *position* looks fine at rest.

This module tries to produce exactly the input that inference needs,
entirely in code:

1. The donor's own geometry is kept (not deleted) but shrunk toward its own
   bounding-box center by `shrink_factor`, so it becomes invisible in-game
   while remaining structurally present for CrimsonForge's proximity-based
   weight inference to reference.
2. The outfit's geometry (already body-conformed and axis-converted by the
   rest of the `sky2cd` pipeline, so it already sits close to where the
   donor's own geometry used to be) is appended alongside it.
3. Each outfit **vertex** is assigned to whichever of the donor's existing
   submeshes owns the single closest donor vertex (a real nearest-neighbor
   search over every donor vertex, via a KD-tree, not just a coarse
   triangle-centroid-vs-submesh-centroid comparison) -- this directly
   matches the granularity CrimsonForge itself will use for weight
   inheritance, so a triangle can no longer be routed into a spatially
   distant submesh just because that submesh's *average* position happened
   to be closer than the true nearest neighbor. Each outfit triangle then
   takes the majority submesh vote of its 3 vertices (falling back to the
   first vertex's assignment on a 3-way tie).

The result is meant to be written out via
:func:`sky2cd.exporters.obj_exporter.write_obj` and fed straight into
CrimsonForge's own "Import + Patch to Game" action -- no Blender required.
Whether CrimsonForge's real weight-inference is actually good enough for a
given outfit is untested here; this is a best-effort automation of the
*mechanical* part of the merge, not a guarantee of correct in-game results.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from sky2cd.meshir import MeshIR

__all__ = ["merge_onto_donor"]


def _bbox_center(positions: np.ndarray) -> np.ndarray:
    return (positions.min(axis=0) + positions.max(axis=0)) / 2.0


def _shrink_toward_center(positions: np.ndarray, shrink_factor: float) -> np.ndarray:
    center = _bbox_center(positions)
    return center + (positions - center) * np.float32(shrink_factor)


def _submesh_groups(triangles: np.ndarray, submesh_ids: np.ndarray | None) -> dict[int, np.ndarray]:
    """Return {submesh_id: triangle_row_indices} for a mesh's triangles.

    If `submesh_ids` is None, the whole mesh is treated as a single group 0.
    """
    if submesh_ids is None:
        return {0: np.arange(triangles.shape[0])}
    groups: dict[int, list[int]] = {}
    for row, sid in enumerate(submesh_ids):
        groups.setdefault(int(sid), []).append(row)
    return {sid: np.array(rows, dtype=np.int64) for sid, rows in groups.items()}


def _vertex_submesh_map(
    triangles: np.ndarray, submesh_ids: np.ndarray | None, vertex_count: int, fallback_id: int
) -> np.ndarray:
    """Return, for each vertex index, the submesh id of the first triangle that uses it.

    Every vertex referenced by at least one triangle gets a real submesh id;
    each `sky2cd`-exported submesh owns its own private, non-overlapping
    vertex range (see `exporters/obj_exporter.py`), so "first triangle that
    uses it" is unambiguous in practice. Any vertex not referenced by any
    triangle (shouldn't normally happen) falls back to `fallback_id`.
    """
    ids_per_tri = (
        submesh_ids.astype(np.int64) if submesh_ids is not None else np.zeros(triangles.shape[0], dtype=np.int64)
    )
    vmap = np.full(vertex_count, -1, dtype=np.int64)
    flat_verts = triangles.astype(np.int64).reshape(-1)
    flat_ids = np.repeat(ids_per_tri, 3)
    for v, sid in zip(flat_verts.tolist(), flat_ids.tolist()):
        if vmap[v] == -1:
            vmap[v] = sid
    vmap[vmap == -1] = fallback_id
    return vmap


def _majority_submesh_per_triangle(triangles: np.ndarray, vertex_submesh: np.ndarray) -> np.ndarray:
    """Pick each triangle's submesh id as the majority vote of its 3 vertices.

    Falls back to the first vertex's assignment when all 3 vertices disagree
    (no true majority) -- deterministic, and a rare case in practice since
    most triangles have all 3 vertices land in the same submesh.
    """
    tri_verts = triangles.astype(np.int64)
    a = vertex_submesh[tri_verts[:, 0]]
    b = vertex_submesh[tri_verts[:, 1]]
    c = vertex_submesh[tri_verts[:, 2]]
    return np.where((a == b) | (a == c), a, np.where(b == c, b, a))


def merge_onto_donor(
    donor: MeshIR,
    outfit: MeshIR,
    *,
    shrink_factor: float = 0.02,
    submesh_strategy: str = "nearest",
) -> MeshIR:
    """Merge `outfit` onto `donor`, shrinking the donor's own geometry to hidden.

    Parameters
    ----------
    donor:
        The existing Crimson Desert item's mesh (e.g. loaded via
        :func:`sky2cd.importers.obj_importer.read_obj` from a CrimsonForge
        export). Its geometry is kept but shrunk to near-invisible, not
        deleted, so its structure remains present for CrimsonForge's own
        positional weight inference.
    outfit:
        The converted Skyrim outfit mesh (typically the `.obj` produced by
        `sky2cd convert`, re-loaded via `read_obj`), assumed to already be
        in the same coordinate space as `donor` (Crimson Desert's Y-up
        convention) -- no axis conversion is applied here.
    shrink_factor:
        Scale factor applied to the donor's geometry around its own
        bounding-box center. Must be in `(0, 1)`; small values (the default,
        0.02) make the donor geometry collapse to a point-like cluster near
        its own center, effectively invisible in-game while remaining
        structurally present.
    submesh_strategy:
        `"nearest"` (default) assigns each outfit vertex to whichever of the
        donor's *existing* submeshes owns the single closest donor vertex
        (real per-vertex nearest-neighbor search, not a coarse average-
        position comparison), then assigns each triangle by majority vote
        of its 3 vertices -- this keeps the total submesh count equal to
        the donor's original count while matching the granularity
        CrimsonForge itself uses for weight inheritance. `"append"` instead
        puts all outfit triangles into a single new submesh id after the
        donor's existing ones.

    Returns
    -------
    A new `MeshIR` with donor (shrunk) + outfit geometry concatenated, and a
    `submesh_ids` array covering every triangle in the merged mesh.
    """
    if submesh_strategy not in ("nearest", "append"):
        raise ValueError(f"submesh_strategy must be 'nearest' or 'append', got {submesh_strategy!r}")
    if not (0.0 < shrink_factor < 1.0):
        raise ValueError(f"shrink_factor must be in (0, 1), got {shrink_factor}")
    if donor.vertex_count == 0:
        raise ValueError("donor mesh has no vertices")
    if outfit.vertex_count == 0:
        raise ValueError("outfit mesh has no vertices")

    donor_positions = _shrink_toward_center(donor.positions.astype(np.float64), shrink_factor)
    donor_groups = _submesh_groups(donor.triangles, donor.submesh_ids)
    donor_group_ids = sorted(donor_groups)

    if submesh_strategy == "append":
        outfit_submesh_ids = np.full(outfit.triangles.shape[0], max(donor_group_ids) + 1, dtype=np.int32)
    else:
        # Real nearest-neighbor search over every individual donor vertex
        # (using the donor's ORIGINAL, unshrunk positions -- the same
        # reference frame CrimsonForge's own weight-inheritance step will
        # use), not just a coarse comparison against each submesh's average
        # position. This matters because CrimsonForge only searches for a
        # donor vertex *within* whichever submesh a new vertex is assigned
        # to -- assigning a whole triangle to the wrong submesh (possible
        # with the old centroid-distance heuristic on complex, multi-
        # submesh donors, e.g. straps/collars/cape pieces mixed in with the
        # main body) makes it inherit skin weights from an unrelated part
        # of the donor and can send the merged geometry flying once the
        # skeleton animates.
        donor_vertex_submesh = _vertex_submesh_map(
            donor.triangles, donor.submesh_ids, donor.vertex_count, donor_group_ids[0]
        )
        donor_tree = cKDTree(donor.positions.astype(np.float64))
        _, nearest_donor_vertex = donor_tree.query(outfit.positions.astype(np.float64), k=1)
        outfit_vertex_submesh = donor_vertex_submesh[nearest_donor_vertex]
        outfit_submesh_ids = _majority_submesh_per_triangle(outfit.triangles, outfit_vertex_submesh).astype(np.int32)

    donor_submesh_ids_full = (
        donor.submesh_ids.astype(np.int32)
        if donor.submesh_ids is not None
        else np.zeros(donor.triangles.shape[0], dtype=np.int32)
    )

    merged_positions = np.concatenate([donor_positions, outfit.positions.astype(np.float64)], axis=0)
    merged_normals = np.concatenate([donor.normals, outfit.normals], axis=0)
    merged_uvs = np.concatenate([donor.uvs, outfit.uvs], axis=0)

    vertex_offset = donor.vertex_count
    merged_triangles = np.concatenate(
        [donor.triangles.astype(np.int64), outfit.triangles.astype(np.int64) + vertex_offset],
        axis=0,
    ).astype(np.uint32)
    merged_submesh_ids = np.concatenate([donor_submesh_ids_full, outfit_submesh_ids], axis=0)

    return MeshIR(
        positions=merged_positions.astype(np.float32),
        normals=merged_normals,
        uvs=merged_uvs,
        triangles=merged_triangles,
        bone_names=list(dict.fromkeys([*donor.bone_names, *outfit.bone_names])),
        name=f"{donor.name}_merged_{outfit.name}",
        submesh_ids=merged_submesh_ids,
    )
