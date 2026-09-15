"""Texture atlas and UV repacking tools for single-material donor compatibility."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from sky2cd.meshir import MeshIR


@dataclass(frozen=True)
class AtlasCell:
    submesh_index: int
    material_index: int
    material_name: str
    col: int
    row: int
    cols: int
    rows: int
    diffuse_path: str | None = None
    normal_path: str | None = None

    @property
    def u_scale(self) -> float:
        return 1.0 / self.cols

    @property
    def v_scale(self) -> float:
        return 1.0 / self.rows

    @property
    def u_offset(self) -> float:
        return self.col / self.cols

    @property
    def v_offset(self) -> float:
        return self.row / self.rows


@dataclass(frozen=True)
class AtlasPlan:
    cells: list[AtlasCell]
    cols: int
    rows: int
    atlas_name: str

    @property
    def is_identity(self) -> bool:
        return len(self.cells) <= 1 and self.cols == 1 and self.rows == 1


def compute_atlas_plan(mesh: MeshIR, atlas_name: str | None = None) -> AtlasPlan:
    """Compute an optimal grid layout for all submeshes in ``mesh``."""
    name = atlas_name or f"{mesh.name}_atlas"
    unique_sids: list[int] = []
    if mesh.submesh_ids is not None and len(mesh.submesh_ids) > 0:
        unique_sids = list(dict.fromkeys(int(s) for s in mesh.submesh_ids))
    elif mesh.materials:
        unique_sids = list(range(len(mesh.materials)))
    else:
        unique_sids = [0]

    count = len(unique_sids)
    if count <= 1:
        mat_name = mesh.materials[0].get("shape", f"{mesh.name}_mat") if mesh.materials else f"{mesh.name}_mat"
        diffuse, normal = _extract_texture_paths(mesh.materials[0] if mesh.materials else None)
        single_cell = AtlasCell(
            submesh_index=0,
            material_index=0,
            material_name=str(mat_name),
            col=0,
            row=0,
            cols=1,
            rows=1,
            diffuse_path=diffuse,
            normal_path=normal,
        )
        return AtlasPlan(cells=[single_cell], cols=1, rows=1, atlas_name=name)

    grid_dim = math.ceil(math.sqrt(count))
    cols = grid_dim
    # Number of rows needed for count elements
    rows = math.ceil(count / cols)

    cells: list[AtlasCell] = []
    for i, sid in enumerate(unique_sids):
        col = i % cols
        row_from_top = i // cols
        row = (rows - 1) - row_from_top
        mat_dict = mesh.materials[sid] if (mesh.materials and 0 <= sid < len(mesh.materials)) else None
        mat_name = mat_dict.get("shape", f"{mesh.name}_submesh{sid}") if mat_dict else f"{mesh.name}_submesh{sid}"
        diffuse, normal = _extract_texture_paths(mat_dict)
        cells.append(
            AtlasCell(
                submesh_index=sid,
                material_index=sid,
                material_name=str(mat_name),
                col=col,
                row=row,
                cols=cols,
                rows=rows,
                diffuse_path=diffuse,
                normal_path=normal,
            )
        )

    return AtlasPlan(cells=cells, cols=cols, rows=rows, atlas_name=name)


def repack_uvs_to_atlas(mesh: MeshIR, plan: AtlasPlan | None = None) -> tuple[MeshIR, AtlasPlan]:
    """Repack UV coordinates of each submesh in ``mesh`` into non-overlapping grid cells.

    Returns the consolidated single-material ``MeshIR`` and the ``AtlasPlan``.
    """
    if plan is None:
        plan = compute_atlas_plan(mesh)

    if plan.is_identity or mesh.uvs is None or mesh.vertex_count == 0:
        return mesh.copy_with(), plan

    # Split vertices if any vertex is shared across submeshes so UV transformation is independent
    separated_mesh = _ensure_disjoint_submesh_vertices(mesh)

    new_uvs = np.array(separated_mesh.uvs, dtype=np.float32, copy=True)
    submesh_ids = separated_mesh.submesh_ids
    if submesh_ids is None:
        return separated_mesh.copy_with(), plan

    for cell in plan.cells:
        tri_mask = submesh_ids == cell.submesh_index
        if not np.any(tri_mask):
            continue
        used_vertices = np.unique(separated_mesh.triangles[tri_mask])
        if len(used_vertices) == 0:
            continue

        # Remap u, v:
        # u' = (u + col) / cols
        # v' = (v + row) / rows
        u = new_uvs[used_vertices, 0]
        v = new_uvs[used_vertices, 1]
        new_uvs[used_vertices, 0] = (u + cell.col) * cell.u_scale
        new_uvs[used_vertices, 1] = (v + cell.row) * cell.v_scale

    unified_mat: dict[str, Any] = {
        "shape": plan.atlas_name,
        "shader": "BSLightingShaderProperty",
        "textures": {
            "diffuse": f"{plan.atlas_name}_diffuse.dds",
            "normal": f"{plan.atlas_name}_normal.dds",
        },
    }

    repacked_mesh = separated_mesh.copy_with(
        uvs=new_uvs,
        materials=[unified_mat],
        submesh_ids=None,
    )
    return repacked_mesh, plan


def _ensure_disjoint_submesh_vertices(mesh: MeshIR) -> MeshIR:
    """Ensure vertices are not shared across different submeshes.

    If vertices are shared, duplicates them so each submesh owns its vertices cleanly.
    """
    if mesh.submesh_ids is None or mesh.vertex_count == 0:
        return mesh

    submesh_ids = np.asarray(mesh.submesh_ids, dtype=np.int32)
    triangles = np.asarray(mesh.triangles, dtype=np.uint32)

    # Check for vertex sharing across submeshes
    vert_submesh_owner = np.full(mesh.vertex_count, -1, dtype=np.int32)
    has_conflict = False

    for tri, sid in zip(triangles, submesh_ids):
        for v in tri:
            owner = vert_submesh_owner[v]
            if owner == -1:
                vert_submesh_owner[v] = sid
            elif owner != sid:
                has_conflict = True
                break
        if has_conflict:
            break

    if not has_conflict:
        return mesh

    # Rebuild disjoint mesh
    new_positions = []
    new_normals = []
    new_uvs = []
    new_bone_indices = []
    new_bone_weights = []
    new_triangles = []
    new_submesh_ids = []

    for sid in np.unique(submesh_ids):
        tri_mask = submesh_ids == sid
        sub_tris = triangles[tri_mask]
        used_verts, inv_indices = np.unique(sub_tris, return_inverse=True)
        offset = sum(len(p) for p in new_positions)

        new_positions.append(mesh.positions[used_verts])
        if mesh.normals is not None:
            new_normals.append(mesh.normals[used_verts])
        if mesh.uvs is not None:
            new_uvs.append(mesh.uvs[used_verts])
        if mesh.bone_indices is not None:
            new_bone_indices.append(mesh.bone_indices[used_verts])
        if mesh.bone_weights is not None:
            new_bone_weights.append(mesh.bone_weights[used_verts])

        remapped_tris = inv_indices.reshape(sub_tris.shape) + offset
        new_triangles.append(remapped_tris)
        new_submesh_ids.append(np.full(len(sub_tris), sid, dtype=np.int32))

    return MeshIR(
        positions=np.concatenate(new_positions, axis=0),
        normals=np.concatenate(new_normals, axis=0) if new_normals else None,
        uvs=np.concatenate(new_uvs, axis=0) if new_uvs else None,
        triangles=np.concatenate(new_triangles, axis=0),
        bone_names=mesh.bone_names,
        bone_indices=np.concatenate(new_bone_indices, axis=0) if new_bone_indices else None,
        bone_weights=np.concatenate(new_bone_weights, axis=0) if new_bone_weights else None,
        materials=mesh.materials,
        name=mesh.name,
        submesh_ids=np.concatenate(new_submesh_ids, axis=0),
    )


def _extract_texture_paths(mat: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not mat or "textures" not in mat or not isinstance(mat["textures"], dict):
        return None, None
    textures = mat["textures"]
    diffuse = textures.get("diffuse") or textures.get("map_Kd") or textures.get("0") or textures.get(0)
    normal = textures.get("normal") or textures.get("map_Bump") or textures.get("bump") or textures.get("1") or textures.get(1)
    return str(diffuse) if diffuse else None, str(normal) if normal else None
