"""Wavefront OBJ importer -- the read-side counterpart to
:mod:`sky2cd.exporters.obj_exporter`.

This exists to support the experimental "no-Blender donor merge" workflow
(see ``sky2cd.donor_merge`` and the README's "Experimental: merge without
Blender" section): loading a donor mesh exported from Crimson Desert by
CrimsonForge back into a :class:`~sky2cd.meshir.MeshIR`, so it can be merged
with a converted outfit and re-exported without ever opening Blender.

Only the OBJ features ``sky2cd`` itself writes (and that CrimsonForge's own
exporter is documented to write) are supported: ``v``/``vt``/``vn``/``f``
lines, ``o``/``g`` groups (ignored beyond bookkeeping), and ``usemtl``
lines used purely to delimit submesh boundaries. Faces are assumed already
triangulated (3 vertices per ``f`` line) -- this matches every OBJ this
project produces or expects to consume.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from sky2cd.meshir import MeshIR

__all__ = ["read_obj"]


def read_obj(path: str | Path, *, name: str | None = None) -> MeshIR:
    """Parse a Wavefront ``.obj`` file into a :class:`MeshIR`.

    A new submesh group starts whenever the ``(o name, usemtl name)`` pair
    changes from what was last seen; the resulting mesh's ``submesh_ids``
    array records, per triangle, which group (by first-seen order, 0-based)
    it belonged to. Tracking both ``o`` and ``usemtl`` (not ``usemtl``
    alone) matters for real donor OBJs exported by CrimsonForge: some real
    multi-submesh donors (e.g. a 3-submesh dress PAC) reuse the exact same
    material name across all of their submeshes -- only their ``o`` line
    differs per submesh -- so a ``usemtl``-only boundary check silently
    collapsed them into a single submesh, discarding the donor's original
    submesh split once merged and re-exported. If the file has no ``o`` or
    ``usemtl`` lines at all, ``submesh_ids`` is left as ``None`` (single
    implicit submesh), matching the default produced by
    :func:`sky2cd.exporters.obj_exporter.write_obj`.

    Only triangulated faces (``f a b c``) are supported; anything else
    raises ``ValueError`` with a clear message rather than silently
    mis-parsing. Positions and normals remain in the OBJ's coordinate system;
    V is unflipped to MeshIR convention, matching CrimsonForge's importer.
    """
    obj_path = Path(path)
    if not obj_path.is_file():
        raise FileNotFoundError(f"OBJ file not found: {obj_path}")

    positions: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    normals: list[tuple[float, float, float]] = []

    # Final per-vertex-attribute-combination arrays, built by de-duplicating
    # (position_index, uv_index, normal_index) triples as OBJ face refs are
    # read -- this correctly expands OBJ's independently-indexed vt/vn onto
    # MeshIR's single-indexed-per-vertex representation.
    vertex_key_to_index: dict[tuple[int, int, int], int] = {}
    out_positions: list[tuple[float, float, float]] = []
    out_uvs: list[tuple[float, float]] = []
    out_normals: list[tuple[float, float, float]] = []
    out_triangles: list[tuple[int, int, int]] = []
    out_submesh_ids: list[int] = []

    submesh_names: list[str] = []
    saw_group_marker = False
    current_o_name: str | None = None
    current_mtl_name: str | None = None
    group_key_to_id: dict[str, int] = {}

    def resolve_index(v_idx: int, vt_idx: int | None, vn_idx: int | None) -> int:
        # OBJ indices are 1-based and may be negative (relative to the end).
        p = v_idx - 1 if v_idx > 0 else len(positions) + v_idx
        t = (vt_idx - 1 if vt_idx > 0 else len(uvs) + vt_idx) if vt_idx is not None else -1
        n = (vn_idx - 1 if vn_idx > 0 else len(normals) + vn_idx) if vn_idx is not None else -1
        key = (p, t, n)
        idx = vertex_key_to_index.get(key)
        if idx is not None:
            return idx
        idx = len(out_positions)
        vertex_key_to_index[key] = idx
        out_positions.append(positions[p])
        out_uvs.append(uvs[t] if t >= 0 and t < len(uvs) else (0.0, 1.0))
        out_normals.append(normals[n] if n >= 0 and n < len(normals) else (0.0, 0.0, 0.0))
        return idx

    for raw_line in obj_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "v":
            positions.append(tuple(float(x) for x in parts[1:4]))  # type: ignore[assignment]
        elif tag == "vt":
            vals = [float(x) for x in parts[1:3]]
            uvs.append((vals[0], vals[1] if len(vals) > 1 else 0.0))
        elif tag == "vn":
            normals.append(tuple(float(x) for x in parts[1:4]))  # type: ignore[assignment]
        elif tag == "o":
            saw_group_marker = True
            current_o_name = parts[1] if len(parts) > 1 else current_o_name
        elif tag == "usemtl":
            saw_group_marker = True
            current_mtl_name = parts[1] if len(parts) > 1 else current_mtl_name
        elif tag == "f":
            face_verts = parts[1:]
            if len(face_verts) != 3:
                raise ValueError(
                    f"Only triangulated faces are supported; got {len(face_verts)} "
                    f"vertices in face '{line}' of {obj_path}"
                )
            tri_indices = []
            for vert in face_verts:
                comps = vert.split("/")
                v_idx = int(comps[0])
                vt_idx = int(comps[1]) if len(comps) > 1 and comps[1] else None
                vn_idx = int(comps[2]) if len(comps) > 2 and comps[2] else None
                tri_indices.append(resolve_index(v_idx, vt_idx, vn_idx))
            out_triangles.append(tuple(tri_indices))  # type: ignore[arg-type]
            # Resolved lazily, only when a face actually uses the current
            # (o, usemtl) pair -- this avoids a stray `o`/`usemtl` line with
            # no faces under it (e.g. a header `o` line preceding the first
            # `usemtl`) from consuming a submesh id that no face ever uses.
            group_key = f"{current_o_name!r}|{current_mtl_name!r}"
            if group_key not in group_key_to_id:
                group_key_to_id[group_key] = len(group_key_to_id)
                submesh_names.append(group_key)
            out_submesh_ids.append(group_key_to_id[group_key])
        # o/g/mtllib/s and anything else are intentionally ignored.

    if not out_positions:
        raise ValueError(f"No vertex data found in OBJ file: {obj_path}")

    # A single group (only one distinct (o, usemtl) pair ever seen) is not
    # meaningfully "multi-submesh" -- only track submesh ids when the file
    # actually distinguishes more than one o/usemtl group.
    submesh_ids_arr = (
        np.array(out_submesh_ids, dtype=np.int32) if saw_group_marker and len(submesh_names) > 1 else None
    )

    return MeshIR(
        positions=np.array(out_positions, dtype=np.float32),
        normals=np.array(out_normals, dtype=np.float32),
        # Both our exporter and CrimsonForge write 1-v for interchange.
        uvs=np.array(out_uvs, dtype=np.float32) * [1, -1] + [0, 1],
        triangles=np.array(out_triangles, dtype=np.uint32),
        name=name or obj_path.stem,
        submesh_ids=submesh_ids_arr,
    )
