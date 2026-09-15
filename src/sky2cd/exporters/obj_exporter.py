"""Wavefront OBJ + MTL exporter for :class:`~sky2cd.meshir.MeshIR`.

This is the actually-usable hand-off point for getting a converted Skyrim
outfit into Crimson Desert as a *replacer* mod. See ``README.md`` ("Reality
check") for the full story, but the short version is:

- Crimson Desert's real mesh geometry binary format (``.pac`` internals) is
  not something ``sky2cd`` can write correctly — nobody in the public
  modding community had it fully reverse engineered as of 2026-09, and
  ``sky2cd.pac.writer`` was always an invented placeholder format.
- **CrimsonForge** (https://github.com/hzeemr/crimsonforge, MIT licensed) is
  a real, actively maintained, community tool that *has* reverse engineered
  the PAC/PAM/PAMLOD vertex geometry layout (quantized positions against a
  bounding box, float16 UVs, submesh tables, bone weights) and can export an
  existing Crimson Desert item to OBJ/FBX, accept an edited/replaced mesh
  back, and patch it into the live game archives with correct
  compression/encryption/checksums — the exact "write bytes back into the
  game" step ``sky2cd`` cannot safely do on its own.

So the intended workflow is:

1. ``sky2cd`` imports the Skyrim ``.nif``/outfit. Built-in presets preserve
   geometry for inspection; fitting needs suitable custom body references.
2. This module writes that deformed mesh out as a plain ``.obj``/``.mtl``
   pair, in Crimson Desert's own coordinate convention (Y-up, Maya-style)
   so it lines up with meshes CrimsonForge exports from the game itself.
3. In Blender: import the target CD armor/weapon item's own baseline OBJ
   (exported *by CrimsonForge*, so its ``.cfmeta.json`` sidecar and donor
   vertex data are present), replace/merge its geometry with the OBJ from
   step 2, re-weight to the CD skeleton, and export back out.
4. Feed that back into CrimsonForge's OBJ/FBX importer + "patch to game" to
   produce a real, loadable replacer mod for the chosen CD slot.

``sky2cd`` does not (and, for licensing/scope reasons, should not) vendor
CrimsonForge itself — it only produces a correctly-oriented OBJ that is
ready to be dropped into that external tool's Blender step.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np

from sky2cd.meshir import MeshIR

__all__ = ["write_obj", "convert_skyrim_to_cd_axes"]


def _format_rows(array, row_fmt: str) -> list[str]:
    """Format a 2D array's rows as `row_fmt % tuple(row)` for each row, fast.

    Uses `numpy.savetxt`'s C-level formatting instead of a Python `for`
    loop + f-string per row -- the same output, but avoids the GC pressure
    of building hundreds of thousands of small Python strings one at a time
    for large outfits.
    """
    if len(array) == 0:
        return []
    buf = io.StringIO()
    np.savetxt(buf, array, fmt=row_fmt)
    return buf.getvalue().splitlines()


def _format_faces(triangles) -> list[str]:
    """Format triangles as OBJ `f a/a/a b/b/b c/c/c` face lines, 1-based indices."""
    if len(triangles) == 0:
        return []
    idx = (triangles.astype(np.int64) + 1).tolist()
    return [f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}" for a, b, c in idx]


def _texture_relative_path(raw_path: str) -> str:
    """Turn a NIF-relative texture path (e.g. ``textures\\armor\\foo.dds``)
    into the ``textures/<basename>`` reference this exporter's ``.mtl``
    files use, matching the sibling ``textures/`` folder that
    :mod:`sky2cd.pipeline` populates next to the ``.obj``/``.mtl`` pair.
    """
    basename = Path(raw_path.replace("\\", "/")).name
    return f"textures/{basename}"


def _texture_map_lines(material: dict | None) -> list[str]:
    """Build ``map_Kd``/``map_Bump`` lines for a submesh's material, if it
    has a diffuse and/or normal texture recorded (see
    :func:`sky2cd.importers.nif_importer._shape_material`)."""
    if not material:
        return []
    lines: list[str] = []
    diffuse = material.get("diffuse_texture")
    if diffuse:
        lines.append(f"map_Kd {_texture_relative_path(diffuse)}")
    normal = material.get("normal_texture")
    if normal:
        rel = _texture_relative_path(normal)
        lines.append(f"map_Bump {rel}")
        lines.append(f"bump {rel}")
    return lines


def convert_skyrim_to_cd_axes(vectors: "list[tuple[float, float, float]] | object") -> object:
    """Rotate Skyrim's Z-up, right-handed NIF space into Crimson Desert's
    Y-up, right-handed (Maya-convention) interchange space.

    The rotation is -90 degrees about X: ``(x, y, z) -> (x, z, -y)``. This
    preserves handedness (the rotation matrix has determinant +1).
    Works on both position and (unnormalized) direction vectors — callers
    normalize normals separately if needed.
    """
    import numpy as np

    arr = np.asarray(vectors, dtype=np.float64)
    out = np.empty_like(arr)
    out[..., 0] = arr[..., 0]
    out[..., 1] = arr[..., 2]
    out[..., 2] = -arr[..., 1]
    return out


def write_obj(
    mesh: MeshIR,
    path: str | Path,
    *,
    axis_convert: bool = True,
    scale: float = 1.0,
) -> Path:
    """Write ``mesh`` as an OBJ + MTL pair compatible with CrimsonForge's
    OBJ importer (``core.mesh_importer.import_obj`` in that project).

    Format details matched to that importer:
      - ``v x y z`` — vertex positions, axis-converted (Skyrim Z-up ->
        Crimson Desert Y-up) and scaled unless ``axis_convert``/``scale``
        say otherwise.
      - ``vt u v`` — UV written with V flipped (``1 - v``), because
        CrimsonForge's importer flips V back on read, expecting its own
        exporter to have flipped it on the way out.
      - ``vn nx ny nz`` — axis-converted, re-normalized normals.
      - One ``o`` group and matching ``usemtl`` per submesh; CrimsonForge
        splits on object boundaries, not on material changes alone.
      - Faces as ``f v/vt/vn`` triples (MeshIR triangles are already
        triangulated, so no fan-triangulation is needed here).

    Returns the path to the written ``.obj`` file.
    """
    import numpy as np

    obj_path = Path(path)
    if obj_path.suffix.lower() != ".obj":
        obj_path = obj_path.with_suffix(".obj")
    obj_path.parent.mkdir(parents=True, exist_ok=True)
    mtl_path = obj_path.with_suffix(".mtl")

    positions = mesh.positions.astype(np.float64) * float(scale)
    normals = mesh.normals.astype(np.float64) if mesh.normals is not None else np.zeros_like(positions)
    uvs = mesh.uvs if mesh.uvs is not None else np.zeros((mesh.vertex_count, 2), dtype=np.float32)

    if axis_convert:
        positions = convert_skyrim_to_cd_axes(positions)
        normals = convert_skyrim_to_cd_axes(normals)

    norm_lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    safe_lengths = np.where(norm_lengths > 1e-12, norm_lengths, 1.0)
    normals = normals / safe_lengths

    material_name = f"{mesh.name}_mat"
    lines = [
        f"# sky2cd export: {mesh.name}",
        "# Written for hand-off to CrimsonForge's OBJ importer -- see",
        "# src/sky2cd/exporters/obj_exporter.py for the full workflow note.",
        f"mtllib {mtl_path.name}",
    ]

    flipped_uvs = np.column_stack([uvs[:, 0].astype(np.float64), 1.0 - uvs[:, 1].astype(np.float64)])

    submesh_ids = mesh.submesh_ids
    material_names = [material_name]
    material_lookup: dict[str, dict | None] = {material_name: (mesh.materials[0] if mesh.materials else None)}
    if submesh_ids is None:
        lines.append(f"usemtl {material_name}")
        lines.append(f"o {mesh.name}")
        # Nine significant digits preserve float32 positions after metre
        # scaling; six decimal places coalesced distinct, close source
        # vertices.
        lines.extend(_format_rows(positions, "v %.9g %.9g %.9g"))
        lines.extend(_format_rows(flipped_uvs, "vt %.6f %.6f"))
        lines.extend(_format_rows(normals, "vn %.6f %.6f %.6f"))
        lines.extend(_format_faces(mesh.triangles))
    else:
        # CrimsonForge's own OBJ importer (core/mesh_importer.py) does NOT
        # use face-referenced global vertex indices to figure out which
        # vertices belong to which submesh. It counts `v`/`vt`/`vn` lines
        # strictly *between* successive `o` markers and treats that count as
        # each submesh's own private, contiguous vertex range. So every
        # submesh must own and emit its OWN vertex/uv/normal block right
        # after its `o` line -- a single global vertex dump before the first
        # `o` marker (the previous behaviour here) makes every submesh after
        # the first see zero vertices in its range, which is exactly the
        # "PAC face in submesh N references an out-of-range vertex" crash
        # this was hit with. This only went unnoticed for single-submesh
        # donors because there's just one `o` group, so it legitimately owns
        # every vertex.
        submesh_ids_arr = np.asarray(submesh_ids, dtype=np.int64)
        unique_ids = list(dict.fromkeys(int(s) for s in submesh_ids))
        material_names = [f"{mesh.name}_submesh{sid}" for sid in unique_ids]
        # submesh id == index into mesh.materials (nif_importer assigns one
        # material per shape, in shape order, matching submesh_ids values).
        material_lookup = {
            mat_name: (mesh.materials[sid] if 0 <= sid < len(mesh.materials) else None)
            for sid, mat_name in zip(unique_ids, material_names)
        }
        order = np.argsort(submesh_ids_arr, kind="stable")
        sorted_ids = submesh_ids_arr[order]
        boundaries = np.searchsorted(sorted_ids, np.asarray(unique_ids, dtype=np.int64))
        boundaries_end = np.searchsorted(sorted_ids, np.asarray(unique_ids, dtype=np.int64), side="right")
        for sid, mat_name, start, end in zip(unique_ids, material_names, boundaries, boundaries_end):
            group_triangles = mesh.triangles[order[start:end]].astype(np.int64)

            # Compact this submesh's own vertex set: every global vertex
            # index referenced by its faces, remapped to a local, per-submesh
            # 0..k-1 range (first-seen order), matching the "vertices owned
            # by this o-group" contract CrimsonForge's importer expects.
            flat_global = group_triangles.reshape(-1)
            local_global_ids = list(dict.fromkeys(int(v) for v in flat_global.tolist()))
            global_to_local = {g: i for i, g in enumerate(local_global_ids)}
            local_positions = positions[local_global_ids]
            local_uvs = flipped_uvs[local_global_ids]
            local_normals = normals[local_global_ids]
            local_triangles = np.vectorize(global_to_local.__getitem__)(group_triangles)

            lines.append(f"o {mat_name}")
            lines.append(f"usemtl {mat_name}")
            lines.extend(_format_rows(local_positions, "v %.9g %.9g %.9g"))
            lines.extend(_format_rows(local_uvs, "vt %.6f %.6f"))
            lines.extend(_format_rows(local_normals, "vn %.6f %.6f %.6f"))
            lines.extend(_format_faces(local_triangles))

    obj_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    mtl_lines = []
    for mat_name in material_names:
        mtl_lines.extend([
            f"newmtl {mat_name}",
            "Ka 1.000 1.000 1.000",
            "Kd 0.800 0.800 0.800",
            "Ks 0.000 0.000 0.000",
            "d 1.0",
            "illum 2",
        ])
        mtl_lines.extend(_texture_map_lines(material_lookup.get(mat_name)))
        mtl_lines.append("")
    mtl_path.write_text("\n".join(mtl_lines).rstrip() + "\n", encoding="utf-8")

    return obj_path
