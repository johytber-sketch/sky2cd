from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile
import warnings

import numpy as np
from scipy.spatial import cKDTree

from sky2cd.archive import discover_meshes, extract_archive, is_archive
from sky2cd.deform.bsw import BSWDeformer
from sky2cd.deform.idw import IDWDeformer
from sky2cd.deform.penetration_fix import fix_penetration
from sky2cd.deform.rigid_mls import RigidMLSDeformer
from sky2cd.deform.normals import recompute_normals
from sky2cd.deform.validation import validate_body_pair, validate_no_collapsed_triangles
from sky2cd.exporters.obj_exporter import write_obj
from sky2cd.importers.nif_importer import import_nif
from sky2cd.meshir import MeshIR, load_meshir, scale_mesh
from sky2cd.pac.writer import write_pac
from sky2cd.presets import resolve_body_config
from sky2cd.slots import build_mapping_report
from sky2cd.textures.atlas import compute_atlas_plan, repack_uvs_to_atlas
from sky2cd.textures.compositor import composite_texture_atlas
from sky2cd.weights.sidecar import reapply_weights


@dataclass(frozen=True)
class ConversionResult:
    pac_path: Path
    report_path: Path
    report: dict


CONVERSION_NOTES = [
    "The .pac file is NOT game-loadable: Crimson Desert's real mesh geometry "
    "binary format is not publicly reverse engineered by sky2cd; this writer "
    "uses an invented placeholder layout. It is kept only for inspection/debugging.",
    "The OBJ is an inspection/interchange mesh, not proof of target-body fit or "
    "game readiness. Validate alignment, body correspondence, target skeleton/weights, "
    "materials and PAC roundtrip separately. Skyrim weights are not a CD rig.",
    "HKX/cloth physics are not converted.",
]
PREVIEW_NOTE = (
    "GEOMETRY/ALIGNMENT PREVIEW ONLY: no body fitting or collision correction. "
    "Bundled references are unvalidated proxies, not authentic target bodies. "
    "Only configured positive unit scaling and one Z-up to Y-up rotation are applied; "
    "target size/pose/origin still require validation. Automatic PAC/DMM packaging is blocked."
)


def convert(
    input_path: str | Path,
    body_config_path: str | Path | dict,
    out_dir: str | Path,
    deformer_name: str = "idw",
    *,
    atlas: bool = False,
) -> ConversionResult:
    input_path = Path(input_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    config = resolve_body_config(body_config_path)

    mode = config.get("geometry_mode", "body_fit")
    if mode not in {"rigid_preview", "body_fit"}:
        raise ValueError(f"Unknown geometry_mode {mode!r}; use rigid_preview or body_fit.")
    for field in ("scale", "output_scale"):
        value = float(config.get(field, 1.0))
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"{field} must be finite and positive.")
    exclusions = config.get("exclude_shapes", [])
    if not isinstance(exclusions, (list, tuple)) or not all(isinstance(name, str) for name in exclusions):
        raise ValueError("exclude_shapes must be a list of exact NIF shape names.")
    notes = list(CONVERSION_NOTES)
    source_body = target_body = None
    if mode == "rigid_preview":
        warnings.warn(PREVIEW_NOTE, UserWarning, stacklevel=2)
        notes.insert(0, PREVIEW_NOTE)
    else:
        source_body = load_meshir(config["source_body"])
        target_body = load_meshir(config["target_body"])
        validate_body_pair(source_body, target_body)
        notes.insert(0, "Custom body fitting is experimental. Numerical reference checks cannot establish anatomical correspondence or provenance.")
    deformer = _make_deformer(deformer_name)
    mapping_report = build_mapping_report([str(slot) for slot in config.get("skyrim_slots", [])])

    if is_archive(input_path):
        with tempfile.TemporaryDirectory(prefix="sky2cd_archive_") as tmp_dir:
            extract_archive(input_path, tmp_dir)
            mesh_paths = discover_meshes(tmp_dir)
            if not mesh_paths:
                raise ValueError(f"No .nif or .meshir.json outfit meshes found in archive: {input_path}")

            converted_meshes = []
            pac_paths = []
            obj_paths = []
            target_body_tree = (
                cKDTree(target_body.positions)
                if target_body is not None and config.get("collision_max_distance") is not None else None
            )
            for mesh_p in mesh_paths:
                rel_parent = mesh_p.relative_to(tmp_dir).parent
                target_sub_dir = out_dir / rel_parent
                target_sub_dir.mkdir(parents=True, exist_ok=True)
                pac_p, mesh_info = _process_mesh(
                    mesh_p, config, target_sub_dir, deformer, source_body, target_body, target_body_tree,
                    texture_root=Path(tmp_dir),
                    atlas=atlas,
                )
                mesh_info["relative_path"] = str(mesh_p.relative_to(tmp_dir))
                pac_paths.append(pac_p)
                obj_paths.append(mesh_info["obj_path"])
                converted_meshes.append(mesh_info)

            report = {
                "input": str(input_path),
                "output_pac": str(pac_paths[0]),
                "output_pacs": [str(p) for p in pac_paths],
                "output_obj": str(obj_paths[0]),
                "output_objs": [str(p) for p in obj_paths],
                "deformer": deformer_name if mode == "body_fit" else "none",
                "geometry_mode": mode,
                "meshes": converted_meshes,
                "slot_mapping": mapping_report.to_dict(),
                "notes": notes,
            }
            report_path = out_dir / "conversion-report.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return ConversionResult(pac_path=pac_paths[0], report_path=report_path, report=report)

    pac_path, mesh_info = _process_mesh(
        input_path, config, out_dir, deformer, source_body, target_body, None,
        texture_root=input_path.parent,
        atlas=atlas,
    )
    report = {
        "input": str(input_path),
        "output_pac": str(pac_path),
        "output_obj": mesh_info["obj_path"],
        "deformer": deformer_name if mode == "body_fit" else "none",
        "geometry_mode": mode,
        "mesh": mesh_info,
        "slot_mapping": mapping_report.to_dict(),
        "notes": notes,
    }
    report_path = out_dir / "conversion-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return ConversionResult(pac_path=pac_path, report_path=report_path, report=report)


def _bounding_box_stats(mesh: MeshIR) -> dict:
    """Bounding box / size summary used for before-vs-after comparisons."""
    mins = mesh.positions.min(axis=0)
    maxs = mesh.positions.max(axis=0)
    size = maxs - mins
    return {
        "min": [round(float(v), 4) for v in mins],
        "max": [round(float(v), 4) for v in maxs],
        "size": [round(float(v), 4) for v in size],
        "vertex_count": mesh.vertex_count,
    }


def _process_mesh(
    mesh_path: Path,
    config: dict,
    out_dir: Path,
    deformer,
    source_body: MeshIR | None,
    target_body: MeshIR | None,
    target_body_tree: cKDTree | None,
    texture_root: Path | None = None,
    atlas: bool = False,
) -> tuple[Path, dict]:
    outfit = _load_input_mesh(mesh_path, exclude_shapes=tuple(config.get("exclude_shapes", [])))
    if not outfit.vertex_count or not np.isfinite(outfit.positions).all():
        raise ValueError(f"Outfit must contain finite, nonempty geometry: {mesh_path}")
    if len(outfit.triangles) and outfit.triangles.max() >= outfit.vertex_count:
        raise ValueError(f"Outfit triangle index is outside its vertex buffer: {mesh_path}")
    before_stats = _bounding_box_stats(outfit)

    outfit = scale_mesh(outfit, float(config.get("scale", 1.0)))
    if config.get("sidecar"):
        outfit = reapply_weights(outfit, outfit, config["sidecar"])

    preview = config.get("geometry_mode", "body_fit") == "rigid_preview"
    if preview:
        fixed = outfit
    else:
        if source_body is None or target_body is None:
            raise ValueError("Body fitting requires validated source and target references.")
        deformed = deformer.deform(source_body, target_body, outfit)
        validate_no_collapsed_triangles(outfit, deformed)
        fixed = recompute_normals(deformed)
        if config.get("collision_max_distance") is not None:
            fixed = fix_penetration(
                fixed, target_body, float(config.get("min_clearance", 1e-4)),
                max_distance=float(config["collision_max_distance"]), tree=target_body_tree,
            )

    # Unit conversion is not a body fit. Built-in 0.0142875 is a starting
    # estimate; alignment with the actual target must be checked separately.
    output_scale = float(config.get("output_scale", 1.0))
    if output_scale != 1.0:
        fixed = scale_mesh(fixed, output_scale)

    stem = mesh_path.stem
    if stem.endswith(".meshir"):
        stem = stem[:-7]

    # Optional "Blender-skip" UV atlas repacking & texture merging for 1-material donors
    diffuse_atlas_path: Path | None = None
    normal_atlas_path: Path | None = None
    if atlas:
        has_multiple_submeshes = (
            fixed.submesh_ids is not None
            and len(np.unique(fixed.submesh_ids)) > 1
        ) or (len(fixed.materials) > 1)
        if has_multiple_submeshes:
            plan = compute_atlas_plan(fixed, atlas_name=f"{stem}_atlas")
            fixed, atlas_plan = repack_uvs_to_atlas(fixed, plan=plan)
            search_dirs: list[Path] = [out_dir, mesh_path.parent]
            if (mesh_path.parent / "textures").is_dir():
                search_dirs.append(mesh_path.parent / "textures")
            if texture_root is not None:
                search_dirs.append(texture_root)
                if (texture_root / "textures").is_dir():
                    search_dirs.append(texture_root / "textures")
            diffuse_atlas_path, normal_atlas_path = composite_texture_atlas(
                atlas_plan, out_dir, search_dirs=search_dirs
            )

    after_stats = _bounding_box_stats(fixed)

    pac_path = write_pac(fixed, out_dir / f"{stem}.pac")
    obj_path = write_obj(fixed, out_dir / f"{stem}.obj")
    copied_textures = _bundle_textures(fixed, texture_root, out_dir)
    mesh_info = {
        "name": fixed.name,
        "source_file": mesh_path.name,
        "vertices": fixed.vertex_count,
        "triangles": int(fixed.triangles.shape[0]),
        "status": "geometry-preview-only" if preview else "experimental-body-fit",
        "flags": ["flagged-rigid-no-physics", "pac-not-game-loadable", "target-rig-unvalidated"]
        + (["not-body-fitted", "automatic-packaging-blocked"] if preview else []),
        "excluded_shape_names": list(config.get("exclude_shapes", [])),
        "collision_correction": "disabled" if preview or config.get("collision_max_distance") is None else "bounded-local-approximation",
        "obj_coordinates": "Y-up: (x, z, -y); configured unit scale; no target pose/origin fit",
        "pac_path": str(pac_path),
        "obj_path": str(obj_path),
        "textures": copied_textures,
        "before": before_stats,
        "after": after_stats,
    }
    if diffuse_atlas_path:
        mesh_info["atlas_diffuse"] = str(diffuse_atlas_path)
    if normal_atlas_path:
        mesh_info["atlas_normal"] = str(normal_atlas_path)
    return pac_path, mesh_info


def pretty_report(report_path: str | Path) -> str:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    slots = report.get("slot_mapping", {})
    lines = [
        f"Input: {report.get('input')}",
        f"Geometry mode: {report.get('geometry_mode', 'legacy / unspecified')}",
    ]
    if "meshes" in report:
        meshes = report["meshes"]
        lines.append(f"Output Directory: {len(meshes)} meshes converted")
        for m in meshes:
            lines.append(f"  - {m.get('name')} ({m.get('vertices')} vertices, {m.get('triangles')} triangles)")
            lines.append(f"      Inspection OBJ ({m.get('status')}): {m.get('obj_path')}")
            lines.append(f"      Legacy .pac (not game-loadable): {m.get('pac_path')}")
            lines.append(_before_after_line(m))
    else:
        mesh = report.get("mesh", {})
        lines.append(f"Inspection OBJ: {report.get('output_obj')}")
        lines.append(f"Legacy .pac (not game-loadable): {report.get('output_pac')}")
        lines.append(f"Mesh: {mesh.get('name')} ({mesh.get('vertices')} vertices, {mesh.get('triangles')} triangles) - {mesh.get('status')}")
        lines.append(_before_after_line(mesh))

    lines.append(f"Deformer: {report.get('deformer')}")
    lines.append(f"Slots: {len(slots.get('mapped', []))} mapped, {len(slots.get('merged', []))} merged, {len(slots.get('unsupported', []))} unsupported")

    single_mesh_flags = report.get("mesh", {}).get("flags")
    if single_mesh_flags:
        lines.append("Flags: " + ", ".join(single_mesh_flags))
    for note in report.get("notes", []):
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def _before_after_line(mesh_info: dict) -> str:
    before = mesh_info.get("before")
    after = mesh_info.get("after")
    if not before or not after:
        return "    (no before/after comparison available)"
    b_size = before["size"]
    a_size = after["size"]
    return (
        "    Before: {}v, size {:.3f}x{:.3f}x{:.3f}  ->  After: {}v, size {:.3f}x{:.3f}x{:.3f}".format(
            before["vertex_count"], b_size[0], b_size[1], b_size[2],
            after["vertex_count"], a_size[0], a_size[1], a_size[2],
        )
    )


def _collect_texture_paths(mesh: MeshIR) -> list[str]:
    """Gather every raw NIF-relative texture path referenced by ``mesh.materials``,
    in first-seen order, deduplicated."""
    seen: dict[str, None] = {}
    for material in mesh.materials:
        for key in ("diffuse_texture", "normal_texture"):
            value = material.get(key)
            if value:
                seen.setdefault(str(value), None)
        textures = material.get("textures")
        if isinstance(textures, dict):
            for value in textures.values():
                if value:
                    seen.setdefault(str(value), None)
    return list(seen.keys())


def _find_texture_file(raw_path: str, texture_root: Path) -> Path | None:
    """Locate the on-disk file for a NIF-relative texture path (e.g.
    ``textures\\armor\\example.dds``) somewhere under ``texture_root``
    (an extracted mod archive, or a loose .nif's parent directory).

    Tries an exact (case-insensitive) relative-path match first, then falls
    back to matching by basename alone -- mods do not always lay textures
    out exactly as the NIF's shader records them.
    """
    normalized = raw_path.replace("\\", "/").lstrip("/").lower()
    basename = Path(normalized).name
    basename_matches: list[Path] = []
    for root, _dirs, files in os.walk(texture_root):
        for f in files:
            candidate = Path(root) / f
            rel = candidate.relative_to(texture_root).as_posix().lower()
            if rel == normalized or rel.endswith("/" + normalized):
                return candidate
            if f.lower() == basename:
                basename_matches.append(candidate)
    return basename_matches[0] if basename_matches else None


def _bundle_textures(mesh: MeshIR, texture_root: Path | None, out_dir: Path) -> list[str]:
    """Copy every texture referenced by ``mesh.materials`` into a
    ``textures/`` subfolder next to the exported ``.obj``/``.mtl`` pair in
    ``out_dir`` so the relative ``map_Kd``/``map_Bump`` paths written by
    :func:`sky2cd.exporters.obj_exporter.write_obj` resolve without any
    manual file wrangling. Returns the list of copied destination paths.
    """
    if texture_root is None or not texture_root.exists():
        return []
    raw_paths = _collect_texture_paths(mesh)
    if not raw_paths:
        return []

    textures_dir = out_dir / "textures"
    copied: list[str] = []
    for raw_path in raw_paths:
        source = _find_texture_file(raw_path, texture_root)
        if source is None:
            continue
        dest = textures_dir / source.name
        if not dest.exists():
            textures_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        copied.append(str(dest))
    return copied


def _load_input_mesh(path: Path, *, exclude_shapes: tuple[str, ...] = ()) -> MeshIR:
    if path.suffix.lower() == ".json" or path.name.endswith(".meshir.json"):
        return load_meshir(path)
    if path.suffix.lower() == ".nif":
        return import_nif(path, exclude_shapes=exclude_shapes)
    raise ValueError(f"Unsupported input mesh format: {path}")


def _make_deformer(name: str):
    key = name.lower().replace("-", "_")
    if key == "idw":
        return IDWDeformer()
    if key in {"rigid_mls", "rigidmls"}:
        return RigidMLSDeformer()
    if key == "bsw":
        return BSWDeformer()
    raise ValueError(f"Unknown deformer '{name}'")
