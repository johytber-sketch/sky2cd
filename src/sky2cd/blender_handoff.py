"""Artist handoff packaging: Skyrim outfit + donor item -> a clean Blender
import bundle, ready for a human modder to fit/clip/weight-paint/rig by hand.

**Why this exists / product boundary this enforces:** sky2cd's real,
confirmed-working capability is safe geometry/axis conversion, donor
inspection/export (materials + textures included, via CrimsonForge), and
DMM packaging -- NOT fully automatic body fitting, weight/rig transfer, or
animation certification (see `sky2cd.presets.require_fitting_config` and
`sky2cd.pipeline.PREVIEW_NOTE`). `auto_replace`/`auto_replace_batch_from_
skyrim` exist for users who supply a real, validated custom body-fit config;
this module is the other, more honest path: hand the artist BOTH meshes
(source outfit + real donor item, materials included) side by side in
Blender and stop there. Nothing here claims a fit, a rig, or a finished mod.

Reuses the same conversion (`sky2cd.pipeline.convert`), donor bridge
(`sky2cd.crimsonforge_bridge`), donor catalog, and multi-piece
selection/auto-select machinery `sky2cd.auto_replace` already uses, so a
multi-piece outfit (e.g. real Sherwood Huntress boots/dress/gloves/hood)
gets one handoff directory per piece in a single call -- no duplicated
piece-matching logic.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from sky2cd import crimsonforge_bridge as cfb
from sky2cd.auto_replace import PieceReplacement, _match_piece_index, _sanitize_piece_tag
from sky2cd.crimsonforge_bridge import CrimsonForgeNotFoundError
from sky2cd.donor_auto_select import auto_select_donors
from sky2cd.donor_catalog import DonorEntry
from sky2cd.pipeline import convert

NOT_FITTED_STATUS = (
    "NOT FITTED. Only conversion's own geometry/axis handling has been applied "
    "(unit scaling + one Z-up to Y-up rotation, per sky2cd.pipeline). No body "
    "fitting, weight transfer, rig binding, clipping resolution, material "
    "finalization, or animation testing has been performed. All of that is the "
    "artist's responsibility before this is a usable, in-game-tested mod."
)


@dataclass(frozen=True)
class HandoffDonorInfo:
    """What we know (and don't) about the donor for one handed-off piece."""

    entry_path: str
    package_group: str
    catalog_display_name: str
    slot: str
    ingame_display_name: str | None = None
    obj_path: Path | None = None
    sidecar_paths: list[Path] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class HandoffPieceResult:
    mesh_selector: str
    relative_path: str
    piece_dir: Path
    source_obj_path: Path
    metadata_path: Path
    donor: HandoffDonorInfo | None = None
    donor_suggestion_path: Path | None = None


@dataclass(frozen=True)
class BlenderHandoffResult:
    conversion_report_path: Path
    out_dir: Path
    pieces: list[HandoffPieceResult]
    unmatched_mesh_pieces: list[str]
    ambiguous_mesh_pieces: list[dict] = field(default_factory=list)
    import_script_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


def _copy_obj_with_sidecars(source_obj_path: Path, dest_dir: Path, dest_name: str = "source") -> Path:
    """Copy an `.obj` plus its sibling `.mtl` and `textures/` folder (if any)
    into `dest_dir`, so the handoff directory is self-contained and doesn't
    depend on any intermediate conversion working directory still existing.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_obj = dest_dir / f"{dest_name}.obj"
    shutil.copy2(source_obj_path, dest_obj)
    mtl_path = source_obj_path.with_suffix(".mtl")
    if mtl_path.is_file():
        shutil.copy2(mtl_path, dest_dir / f"{dest_name}.mtl")
        # obj_exporter writes "mtllib <name>.mtl" using the ORIGINAL stem;
        # rewrite the copy's mtllib line so it points at the renamed file.
        text = dest_obj.read_text(encoding="utf-8")
        text = text.replace(f"mtllib {mtl_path.name}", f"mtllib {dest_name}.mtl")
        dest_obj.write_text(text, encoding="utf-8")
    textures_dir = source_obj_path.parent / "textures"
    if textures_dir.is_dir():
        shutil.copytree(textures_dir, dest_dir / "textures", dirs_exist_ok=True)
    return dest_obj


def _resolve_pieces(
    conversion,
    pieces: list[PieceReplacement] | None,
) -> tuple[list[str], list[Path], list[PieceReplacement], list[dict]]:
    """Mirror `sky2cd.auto_replace.auto_replace_batch_from_skyrim`'s piece
    discovery + (optional) auto-selection so callers get identical behavior
    (and identical ambiguous/unmatched reporting) for the handoff path.
    """
    meshes = conversion.report.get("meshes")
    if not meshes:
        if pieces is not None and len(pieces) > 1:
            raise ValueError(
                "This input has only a single mesh piece (no separate boots/gloves/hood/etc.), "
                "so more than one --piece isn't applicable."
            )
        relative_paths = ["<single piece>"]
        piece_obj_paths = [Path(conversion.report["output_obj"])]
    else:
        relative_paths = [m["relative_path"] for m in meshes]
        piece_obj_paths = [Path(m["obj_path"]) for m in meshes]

    ambiguous_mesh_pieces: list[dict] = []
    if pieces is None:
        guesses = auto_select_donors(relative_paths)
        resolved_pieces: list[PieceReplacement] = []
        for relative_path, guess in zip(relative_paths, guesses):
            if guess.resolved is not None:
                resolved_pieces.append(PieceReplacement(mesh_selector=relative_path, donor=guess.resolved))
            elif guess.ambiguous:
                ambiguous_mesh_pieces.append(
                    {
                        "relative_path": relative_path,
                        "guessed_slot": guess.guessed_slot,
                        "candidate_donor_ids": [candidate.id for candidate in guess.candidates],
                    }
                )
        pieces = resolved_pieces

    return relative_paths, piece_obj_paths, (pieces or []), ambiguous_mesh_pieces


def _safe_dir_tag(mesh_selector: str) -> str:
    """`_sanitize_piece_tag` strips directory separators but not other
    filesystem-unsafe characters (e.g. the literal `"<single piece>"`
    placeholder used for non-archive inputs) -- strip those too so the
    per-piece handoff directory name is always a valid Windows path.
    """
    tag = _sanitize_piece_tag(mesh_selector)
    return "".join(c if (c.isalnum() or c in " _-()'.") else "_" for c in tag).strip("_ ") or "piece"


_IMPORT_SCRIPT_HEADER = '''\
"""Blender artist-review import script, generated by `sky2cd blender-handoff`.

Run this INSIDE Blender (Scripting tab -> Run Script, or
`blender --background --python import_script.py`). It imports the converted
Skyrim source mesh(es) and their real donor item(s) side by side, each with
a distinct viewport color so they're easy to tell apart, and labels every
object clearly.

THIS SCRIPT DOES NOT FIT, WEIGHT-PAINT, RIG, OR VALIDATE ANYTHING. It is
purely a visual starting point for manual artist work: alignment/fitting,
clipping fixes, weight transfer to the Crimson Desert rig, material review,
and in-game/animation testing all still need to happen by hand afterward.
"""
import bpy


def _import_obj(path, label, color):
    if not path:
        return None
    try:
        bpy.ops.wm.obj_import(filepath=path)
    except AttributeError:
        # Older Blender (<3.6) uses the legacy importer name instead.
        bpy.ops.import_scene.obj(filepath=path)
    imported = list(bpy.context.selected_objects)
    for obj in imported:
        obj.name = label
        mat = bpy.data.materials.new(name=f"{label}_preview_color")
        mat.diffuse_color = color
        if obj.data and hasattr(obj.data, "materials"):
            obj.data.materials.clear()
            obj.data.materials.append(mat)
    return imported


'''


def _build_import_script(pieces: list[HandoffPieceResult]) -> str:
    lines = [_IMPORT_SCRIPT_HEADER]
    # Materially distinct, non-photoreal preview colors -- source pieces get
    # a warm red-orange, donors get a cool blue -- purely so the two mesh
    # sources are trivially distinguishable at a glance, not a material claim.
    for piece in pieces:
        source_path = piece.source_obj_path.as_posix()
        label = f"sky2cd_source_{_safe_dir_tag(piece.mesh_selector)}"
        lines.append(f'_import_obj(r"{source_path}", "{label}", (0.8, 0.2, 0.1, 1.0))')
        if piece.donor is not None and piece.donor.obj_path is not None:
            donor_path = piece.donor.obj_path.as_posix()
            donor_label = f"sky2cd_donor_{_safe_dir_tag(piece.mesh_selector)}"
            lines.append(f'_import_obj(r"{donor_path}", "{donor_label}", (0.1, 0.3, 0.8, 1.0))')
        elif piece.donor is not None and piece.donor.error:
            lines.append(f"# Donor for '{piece.mesh_selector}' was NOT exported: {piece.donor.error}")
    lines.append("")
    lines.append('print("sky2cd handoff import complete -- see the piece metadata.json files for details.")')
    return "\n".join(lines) + "\n"


def build_blender_handoff(
    skyrim_mesh_path: str | Path,
    body_config_path: str | Path | dict,
    pieces: list[PieceReplacement] | None,
    packages_path: str | Path | None,
    crimsonforge_home: str | Path | None,
    out_dir: str | Path,
    *,
    deformer_name: str = "idw",
    atlas: bool = False,
    resolve_ingame_names: bool = True,
) -> BlenderHandoffResult:
    """Build a clean, self-contained Blender handoff directory for an artist.

    Unlike `sky2cd.auto_replace`, this never packages a DMM mod and never
    requires a validated custom body-fit config -- `body_config_path` may be
    a bundled geometry-preview preset (e.g. `"fem_kliff"`); this path never
    calls `sky2cd.presets.require_fitting_config`, since nothing here is
    packaged as a finished replacer.

    Args:
        skyrim_mesh_path: Skyrim outfit mesh or archive (same as
            `sky2cd.pipeline.convert`).
        body_config_path: body preset name/path/dict; only used for the
            geometry/axis conversion, not a fit guarantee.
        pieces: one `PieceReplacement(mesh_selector, donor)` per piece, or
            `None` to auto-select a donor per piece the same way
            `auto_replace_batch_from_skyrim` does (ambiguous/unmatched
            pieces are reported, not guessed further).
        packages_path, crimsonforge_home: real game `packages/` dir + a
            CrimsonForge install's source root. Both optional: if either is
            missing, every piece's handoff still includes the converted
            source mesh, just with no donor OBJ/sidecars/in-game name (each
            piece's `donor.error` explains why).
        out_dir: directory to write the handoff bundle into.
        deformer_name, atlas: passed through to `sky2cd.pipeline.convert`.
        resolve_ingame_names: if donors are available, also resolve each
            one's real in-game display name via
            `sky2cd.crimsonforge_bridge.build_item_name_resolver` (reused,
            not duplicated).

    Returns:
        BlenderHandoffResult with one HandoffPieceResult per piece, any
        unmatched/ambiguous pieces, the generated Blender import script
        path, and any top-level warnings (e.g. CrimsonForge/game install
        not usable at all).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    warning_list: list[str] = []

    convert_dir = out_dir / "converted"
    conversion = convert(skyrim_mesh_path, body_config_path, convert_dir, deformer_name, atlas=atlas)
    relative_paths, piece_obj_paths, resolved_pieces, ambiguous_mesh_pieces = _resolve_pieces(conversion, pieces)

    if not resolved_pieces:
        detail = f" Ambiguous piece(s): {ambiguous_mesh_pieces}." if ambiguous_mesh_pieces else ""
        raise ValueError(
            "Auto-donor-selection could not confidently resolve a donor for any of the "
            f"{len(relative_paths)} piece(s) found in this outfit.{detail} Pass an explicit "
            "`pieces`/`--piece \"selector=donor_id\"` for each piece instead, or omit "
            "--packages-path/--crimsonforge-home entirely for a donor-less, source-only handoff."
        )

    matched_indices: set[int] = set()
    piece_specs: list[tuple[PieceReplacement, int]] = []
    for piece in resolved_pieces:
        index = _match_piece_index(relative_paths, piece.mesh_selector)
        matched_indices.add(index)
        piece_specs.append((piece, index))
    unmatched_mesh_pieces = [rp for i, rp in enumerate(relative_paths) if i not in matched_indices]

    cf = None
    vfs = None
    name_resolver = None
    if packages_path and crimsonforge_home:
        try:
            cf = cfb.load_crimsonforge_modules(crimsonforge_home)
            vfs = cfb.open_vfs(cf, packages_path)
            if resolve_ingame_names:
                name_resolver = cfb.build_item_name_resolver(cf, vfs)
        except (CrimsonForgeNotFoundError, FileNotFoundError, ImportError, StopIteration) as exc:
            warning_list.append(
                f"CrimsonForge/game install not usable ({exc}); every piece's handoff will be "
                "source-only (no donor OBJ/sidecars)."
            )
            cf = vfs = name_resolver = None
    else:
        warning_list.append(
            "--packages-path/--crimsonforge-home not given; every piece's handoff is source-only "
            "(no donor OBJ/sidecars)."
        )

    handoff_root = out_dir / "handoff"
    piece_results: list[HandoffPieceResult] = []
    for piece_index, (piece, mesh_index) in enumerate(piece_specs):
        tag = _safe_dir_tag(piece.mesh_selector)
        piece_dir = handoff_root / f"{piece_index:02d}_{tag}"
        source_obj_path = _copy_obj_with_sidecars(piece_obj_paths[mesh_index], piece_dir, "source")

        donor_info: HandoffDonorInfo | None = None
        if piece.donor is not None:
            donor: DonorEntry = piece.donor
            donor_obj_path: Path | None = None
            sidecar_paths: list[Path] = []
            donor_error: str | None = None
            ingame_name: str | None = None
            if vfs is not None:
                try:
                    donor_pac_bytes = cfb.read_donor_pac_bytes(vfs, donor.entry_path, donor.package_group)
                    donor_export_dir = piece_dir / "donor"
                    donor_export_dir.mkdir(parents=True, exist_ok=True)
                    exported = cfb.export_donor_obj(cf, donor_pac_bytes, donor.entry_path, donor_export_dir)
                    donor_obj_path = _copy_obj_with_sidecars(exported, donor_export_dir, "donor")
                    sidecar_files = cfb.read_sidecar_files(vfs, donor.entry_path, donor.package_group)
                    sidecar_dir = piece_dir / "donor_sidecars"
                    sidecar_dir.mkdir(parents=True, exist_ok=True)
                    for rel_path, data in sidecar_files.items():
                        sidecar_path = sidecar_dir / Path(rel_path).name
                        sidecar_path.write_bytes(data)
                        sidecar_paths.append(sidecar_path)
                    if name_resolver is not None:
                        ingame_name = name_resolver.resolve(donor.entry_path)
                except (FileNotFoundError, CrimsonForgeNotFoundError) as exc:
                    donor_error = str(exc)
            else:
                donor_error = "no CrimsonForge/game install available for this run"

            donor_info = HandoffDonorInfo(
                entry_path=donor.entry_path,
                package_group=donor.package_group,
                catalog_display_name=donor.display_name,
                slot=donor.slot,
                ingame_display_name=ingame_name,
                obj_path=donor_obj_path,
                sidecar_paths=sidecar_paths,
                error=donor_error,
            )

        metadata = {
            "mesh_selector": piece.mesh_selector,
            "relative_path": relative_paths[mesh_index],
            "source_obj": str(source_obj_path),
            "status": NOT_FITTED_STATUS,
            "conversion_notes": conversion.report.get("notes", []),
            "donor": None
            if donor_info is None
            else {
                "entry_path": donor_info.entry_path,
                "package_group": donor_info.package_group,
                "catalog_display_name": donor_info.catalog_display_name,
                "slot": donor_info.slot,
                "ingame_display_name": donor_info.ingame_display_name,
                "obj": str(donor_info.obj_path) if donor_info.obj_path else None,
                "sidecars": [str(p) for p in donor_info.sidecar_paths],
                "error": donor_info.error,
            },
            "warnings": list(warning_list),
        }
        metadata_path = piece_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        donor_suggestion_path: Path | None = None
        try:
            from sky2cd.donor_recommendation import (
                DonorEvidence,
                bounds_compatibility,
                guess_slot_from_path,
                rank_donors,
                write_recommendation_json,
            )
            from sky2cd.donor_catalog import list_catalog
            from sky2cd.importers.obj_importer import read_obj

            evidence_by_id: dict[str, DonorEvidence] = {}
            recommendation_catalog = list_catalog()
            suggestion_slot = guess_slot_from_path(relative_paths[mesh_index])
            if suggestion_slot is None and piece.donor is not None:
                suggestion_slot = piece.donor.slot
            if donor_info is not None:
                if all(entry.id != piece.donor.id for entry in recommendation_catalog):
                    recommendation_catalog.append(piece.donor)
                compatibility = None
                if donor_info.obj_path is not None:
                    compatibility = bounds_compatibility(
                        read_obj(source_obj_path),
                        read_obj(donor_info.obj_path),
                    )
                evidence_by_id[piece.donor.id] = DonorEvidence(
                    verified=True if donor_info.obj_path is not None else None,
                    resolved_package_group=donor_info.package_group,
                    ingame_name=donor_info.ingame_display_name,
                    sidecar_paths=tuple(str(path) for path in donor_info.sidecar_paths),
                    bounds_compatibility=compatibility,
                    inspection_error=donor_info.error or "",
                )
            recommendations = rank_donors(
                relative_paths[mesh_index],
                catalog=recommendation_catalog,
                evidence_by_id=evidence_by_id,
                inferred_slot=suggestion_slot,
            )
            donor_suggestion_path = write_recommendation_json(
                piece_dir / "donor_suggestion.json",
                relative_paths[mesh_index],
                recommendations,
                inferred_slot=suggestion_slot,
            )
        except ValueError as exc:
            warning_list.append(
                f"No donor suggestion sidecar for '{relative_paths[mesh_index]}': {exc}"
            )

        piece_results.append(
            HandoffPieceResult(
                mesh_selector=piece.mesh_selector,
                relative_path=relative_paths[mesh_index],
                piece_dir=piece_dir,
                source_obj_path=source_obj_path,
                metadata_path=metadata_path,
                donor=donor_info,
                donor_suggestion_path=donor_suggestion_path,
            )
        )

    import_script_path = handoff_root / "import_script.py"
    import_script_path.parent.mkdir(parents=True, exist_ok=True)
    import_script_path.write_text(_build_import_script(piece_results), encoding="utf-8")

    return BlenderHandoffResult(
        conversion_report_path=conversion.report_path,
        out_dir=out_dir,
        pieces=piece_results,
        unmatched_mesh_pieces=unmatched_mesh_pieces,
        ambiguous_mesh_pieces=ambiguous_mesh_pieces,
        import_script_path=import_script_path,
        warnings=warning_list,
    )
