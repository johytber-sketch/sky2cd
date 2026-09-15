"""End-to-end orchestration: Skyrim outfit -> real, droppable DMM mod.

This is the "make it automated like a tool" step: given a Skyrim outfit mesh
and a donor catalog entry (or an explicit VFS entry path), this module drives
every step that previously required running two separate programs by hand:

1. `sky2cd.pipeline.convert` -- Skyrim mesh -> body-conformed, scaled `.obj`.
2. `sky2cd.crimsonforge_bridge` -- read the real donor `.pac` straight out of
   the user's live game install, export it to `.obj` via CrimsonForge, merge
   the converted outfit onto it (`sky2cd.donor_merge.merge_onto_donor`), then
   rebuild a real, loadable `.pac` via CrimsonForge's own importer/builder --
   no manual CrimsonForge GUI step required.
3. `sky2cd.dmm_package.build_dmm_package` -- package the rebuilt `.pac` as a
   DMM-compatible loose-file mod folder, ready to drop into a `mods/` folder.

Nothing here ever writes to the user's actual game install; the donor `.pac`
is only *read*, in memory, to build the merged replacer.
"""

from __future__ import annotations

import os
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from sky2cd import crimsonforge_bridge as cfb
from sky2cd.decimate import decimate_mesh, weld_duplicate_vertices
from sky2cd.dmm_package import DmmAsset, DmmPackageResult, build_dmm_package
from sky2cd.donor_auto_select import auto_select_donors
from sky2cd.donor_catalog import DonorEntry
from sky2cd.donor_merge import merge_onto_donor
from sky2cd.exporters.obj_exporter import write_obj
from sky2cd.importers.obj_importer import read_obj
from sky2cd.presets import require_fitting_config, resolve_body_config
from sky2cd.pipeline import convert

# Safety margin below the real 65,535-vertex-per-submesh PAC limit
# (`sky2cd.crimsonforge_bridge._PAC_MAX_VERTICES_PER_SUBMESH`), reserved for
# any small vertex-count growth CrimsonForge's own import/rebuild step may
# introduce (e.g. splitting a vertex that has attributes it can't share
# across a UV seam). Conservative but cheap: costs a few hundred vertices of
# extra decimation at most.
_VERTEX_BUDGET_SAFETY_MARGIN = 500


@dataclass(frozen=True)
class AutoReplaceResult:
    conversion_report_path: Path
    merged_obj_path: Path
    rebuilt_pac_path: Path
    dmm_package: DmmPackageResult
    outfit_vertex_count_before: int
    outfit_vertex_count_after: int
    decimated: bool
    sidecar_file_paths: list[str]
    selected_mesh_piece: str
    unselected_mesh_pieces: list[str]


@dataclass(frozen=True)
class PieceReplacement:
    """One (which piece, which donor) pairing for a batch multi-piece run.

    `mesh_selector` is matched the same way as `auto_replace_from_skyrim`'s
    single-piece `mesh_selector` argument: a case-insensitive substring
    against each discovered piece's relative path (e.g. `"gloves"`).
    """

    mesh_selector: str
    donor: DonorEntry


@dataclass(frozen=True)
class PieceResult:
    """Per-piece detail inside a `BatchAutoReplaceResult`."""

    mesh_selector: str
    selected_mesh_piece: str
    donor_entry_path: str
    merged_obj_path: Path
    rebuilt_pac_path: Path
    outfit_vertex_count_before: int
    outfit_vertex_count_after: int
    decimated: bool


@dataclass(frozen=True)
class BatchAutoReplaceResult:
    conversion_report_path: Path
    dmm_package: DmmPackageResult
    pieces: list[PieceResult]
    unmatched_mesh_pieces: list[str]
    sidecar_file_paths: list[str]
    # Pieces where auto-donor-selection guessed a slot but found MORE THAN
    # ONE catalog donor for it (so nothing was auto-picked); each dict has
    # "relative_path", "guessed_slot", "candidate_donor_ids". Always empty
    # when `pieces` was passed explicitly (auto-selection didn't run).
    ambiguous_mesh_pieces: list[dict] = field(default_factory=list)


def _select_outfit_obj_path(conversion, mesh_selector: str | None) -> tuple[Path, list[str]]:
    """Pick which converted `.obj` to use when the input had multiple pieces.

    **Real, confirmed gap this fixes:** a Skyrim outfit archive can contain
    several separate armor pieces (e.g. the real Sherwood Huntress mod tested
    live has `Boots_1.nif`, `Dress_1.nif`, `Gloves_1.nif`, `Hood_1.nif` --
    four distinct meshes, not one). `sky2cd.pipeline.convert` already
    converts every piece it finds in an archive, but this function previously
    always silently took the *first* one (`output_objs[0]`) and merged only
    that single piece onto one donor, discarding the rest with no warning --
    the most likely path to an outfit "looking wrong" for any multi-piece
    Skyrim mod, since 3 of 4 real pieces were thrown away unnoticed.

    `mesh_selector`, if given, is matched case-insensitively as a substring
    against each discovered piece's relative path (e.g. `"gloves"` matches
    `..."Gloves_1.nif"`); the first match is used. If `None`, the first
    discovered piece is used (preserving old single-piece behavior), but the
    caller can inspect `AutoReplaceResult.unselected_mesh_pieces` to see what
    else was available and run again with a different `--mesh-selector` (and
    a matching-slot donor) to cover the rest of a multi-piece outfit.

    Returns `(chosen_obj_path, other_piece_relative_paths)`.
    """
    meshes = conversion.report.get("meshes")
    if not meshes:
        # Non-archive input: exactly one piece, no selection possible/needed.
        return Path(conversion.report["output_obj"]), []

    relative_paths = [m["relative_path"] for m in meshes]
    if mesh_selector is None:
        chosen_index = 0
    else:
        chosen_index = _match_piece_index(relative_paths, mesh_selector)

    chosen_obj_path = Path(meshes[chosen_index]["obj_path"])
    others = [rp for i, rp in enumerate(relative_paths) if i != chosen_index]
    return chosen_obj_path, others


def _match_piece_index(relative_paths: list[str], mesh_selector: str) -> int:
    """Return the index of the first piece whose relative path contains
    `mesh_selector` (case-insensitive substring match). Raises `ValueError`
    if nothing matches.
    """
    needle = mesh_selector.lower()
    matches = [i for i, rp in enumerate(relative_paths) if needle in rp.lower()]
    if not matches:
        raise ValueError(
            f"mesh_selector={mesh_selector!r} matched none of the {len(relative_paths)} "
            f"piece(s) found in this outfit: {relative_paths}"
        )
    return matches[0]


def _sanitize_piece_tag(mesh_selector: str) -> str:
    """Make `mesh_selector` safe to use as a filename fragment.

    **Real bug this fixes:** when auto-selecting donors (`pieces=None`),
    `mesh_selector` is set to a piece's full archive-relative path (e.g.
    `"[My Outfit]\\meshes\\Armor\\[My Outfit]\\Boots_1.nif"`, needed so
    `_match_piece_index` finds that exact piece unambiguously even when two
    pieces share a filename in different subfolders) -- using that path
    directly as part of an output filename (`out_dir / f"{tag}_{donor_name}"`)
    tries to create nested directories that don't exist and fails with a
    real, confirmed live "No such file or directory" error. Strip directory
    separators and only keep the final path component (the actual mesh
    filename) so the tag stays informative but filesystem-safe.
    """
    return Path(mesh_selector).name or mesh_selector


def _process_one_piece_worker(
    crimsonforge_home: str | Path,
    packages_path: str | Path,
    outfit_obj_path: Path,
    donor: DonorEntry,
    out_dir: Path,
    piece_tag: str,
    shrink_factor: float,
    decimation_agg: float,
) -> tuple[DmmAsset, dict[str, bytes], int, int, bool, Path, Path]:
    """Process-pool worker entry point for one piece of a batch conversion.

    **Real perf win, confirmed via live testing**: CrimsonForge's own
    `rebuild_pac()` step (skin-weight inference + vertex quantization/
    packing) is the actual dominant cost of a multi-piece conversion --
    ~1.5-4 minutes *per piece*, confirmed via live process CPU monitoring
    against the real Sherwood Huntress 4-piece outfit -- not anything in
    sky2cd's own Python code. Since each `(piece, donor)` pair is fully
    independent (separate donor PAC, separate merge, separate rebuild),
    running them concurrently across CPU cores via `ProcessPoolExecutor`
    turns N sequential rebuilds into ~1 rebuild's wall time (bounded by core
    count).

    Must be a plain, importable module-level function (not a closure or
    bound method) so `ProcessPoolExecutor` can pickle it across the process
    boundary; `cf`/`vfs` handles themselves are NOT picklable, so each
    worker process loads its own CrimsonForge modules and opens its own VFS
    handle here rather than receiving one from the parent process. The
    ~5-10s one-time PAMT-parsing cost this repeats per worker is negligible
    next to the multi-minute rebuild it's parallelizing.
    """
    cf = cfb.load_crimsonforge_modules(crimsonforge_home)
    vfs = cfb.open_vfs(cf, packages_path)
    return _process_one_piece(cf, vfs, outfit_obj_path, donor, out_dir, piece_tag, shrink_factor, decimation_agg)


def _process_one_piece(
    cf,
    vfs,
    outfit_obj_path: Path,
    donor: DonorEntry,
    out_dir: Path,
    piece_tag: str,
    shrink_factor: float,
    decimation_agg: float,
) -> tuple[DmmAsset, dict[str, bytes], int, int, bool, Path, Path]:
    """Merge one converted outfit piece onto one donor and rebuild its `.pac`.

    Shared by both `auto_replace_from_skyrim` (one piece) and
    `auto_replace_batch_from_skyrim` (many pieces in one run). `piece_tag` is
    a filesystem-safe string used to keep each piece's intermediate
    `merged_*.obj`/`.pac` filenames distinct within a shared `out_dir`.

    Returns `(asset, sidecar_files, vertex_count_before, vertex_count_after,
    decimated, merged_obj_path, rebuilt_pac_path)`.
    """
    outfit_mesh = read_obj(outfit_obj_path)
    outfit_vertex_count_before = outfit_mesh.vertex_count

    donor_pac_bytes = cfb.read_donor_pac_bytes(vfs, donor.entry_path, donor.package_group)
    # Real, confirmed-working DMM mods ("Proxima Shell Mesh Mod", inspected
    # directly on the user's live DMM install) ship each replaced item's real
    # `.pac_xml` (material/skin bindings) and texture `.dds` sidecars
    # alongside the `.pac` -- carry them over unmodified: we don't touch
    # materials/textures, only geometry.
    sidecar_files = cfb.read_sidecar_files(vfs, donor.entry_path, donor.package_group)

    donor_export_dir = out_dir / "donor_export" / piece_tag
    donor_export_dir.mkdir(parents=True, exist_ok=True)
    donor_obj_path = cfb.export_donor_obj(cf, donor_pac_bytes, donor.entry_path, donor_export_dir)
    donor_mesh = read_obj(donor_obj_path)

    # Real PAC-format constraint (see crimsonforge_bridge._PAC_MAX_VERTICES_PER_SUBMESH):
    # a rebuilt submesh can hold at most 65,535 vertices.
    budget = cfb._PAC_MAX_VERTICES_PER_SUBMESH - donor_mesh.vertex_count - _VERTEX_BUDGET_SAFETY_MARGIN
    decimated = False
    if outfit_mesh.vertex_count > budget:
        outfit_mesh = weld_duplicate_vertices(outfit_mesh)
    if outfit_mesh.vertex_count > budget:
        if budget < 4:
            raise ValueError(
                f"Donor '{donor.entry_path}' alone already has {donor_mesh.vertex_count} vertices, "
                f"leaving no usable budget under the real {cfb._PAC_MAX_VERTICES_PER_SUBMESH}-vertex "
                "PAC submesh limit; pick a lower-vertex-count donor."
            )
        result = decimate_mesh(outfit_mesh, budget, agg=decimation_agg)
        outfit_mesh = result.mesh
        decimated = True
    outfit_vertex_count_after = outfit_mesh.vertex_count

    merged_mesh = merge_onto_donor(donor_mesh, outfit_mesh, shrink_factor=shrink_factor)
    merged_obj_name = "merged.obj" if piece_tag == "piece" else f"merged_{piece_tag}.obj"
    merged_obj_path = write_obj(merged_mesh, out_dir / merged_obj_name, axis_convert=False)

    rebuilt_pac_bytes = cfb.rebuild_pac(cf, merged_obj_path, donor_pac_bytes)
    pac_name = Path(donor.entry_path).name if piece_tag == "piece" else f"{piece_tag}_{Path(donor.entry_path).name}"
    rebuilt_pac_path = out_dir / pac_name
    rebuilt_pac_path.write_bytes(rebuilt_pac_bytes)

    asset = DmmAsset(
        entry_path=donor.entry_path,
        pac_bytes=rebuilt_pac_bytes,
        package_group=donor.package_group,
        vertices=merged_mesh.vertex_count,
        faces=int(merged_mesh.triangles.shape[0]),
        source_obj_path=str(merged_obj_path),
        note=f"Replaces: {donor.display_name}",
    )
    return (
        asset,
        sidecar_files,
        outfit_vertex_count_before,
        outfit_vertex_count_after,
        decimated,
        merged_obj_path,
        rebuilt_pac_path,
    )


def auto_replace_from_skyrim(
    skyrim_mesh_path: str | Path,
    body_config_path: str | Path | dict,
    donor: DonorEntry,
    packages_path: str | Path,
    crimsonforge_home: str | Path,
    out_dir: str | Path,
    *,
    title: str,
    author: str = "sky2cd",
    version: str = "1.0.0",
    game_build: str = "",
    description: str = "",
    deformer_name: str = "idw",
    shrink_factor: float = 0.02,
    decimation_agg: float = 7.0,
    mesh_selector: str | None = None,
    atlas: bool = False,
) -> AutoReplaceResult:
    """Convert a Skyrim outfit and package it as a real, droppable DMM mod.

    Args:
        skyrim_mesh_path: Skyrim `.nif`/`.meshir.json` outfit mesh, or an
            archive containing one (same inputs `sky2cd convert` accepts).
            If the archive has multiple pieces (e.g. separate boots/gloves/
            hood/body meshes), see `mesh_selector`.
        body_config_path: body preset name/path/dict (e.g. `"fem_kliff"`).
        donor: the `DonorEntry` (from `sky2cd.donor_catalog`) to replace.
        packages_path: path to the real game's `packages/` directory.
        crimsonforge_home: path to a CrimsonForge install's Python source
            root (see `sky2cd.crimsonforge_bridge.find_crimsonforge_home`).
        out_dir: working directory for intermediate + final output.
        title, author, version, game_build, description: DMM package
            metadata (see `sky2cd.dmm_package.build_dmm_package`).
        deformer_name: passed through to `sky2cd.pipeline.convert`.
        shrink_factor: passed through to `sky2cd.donor_merge.merge_onto_donor`.
        decimation_agg: `fast_simplification` aggressiveness, only used if
            welding alone isn't enough to fit the real PAC vertex-per-submesh
            limit (see `sky2cd.decimate.decimate_mesh`).
        mesh_selector: when the input has multiple pieces, a case-insensitive
            substring matched against each piece's relative path to pick
            which one to merge onto `donor` (e.g. `"gloves"`). `None` (the
            default) picks the first piece found -- run this function again
            with a different `mesh_selector` and a donor matching that
            piece's slot to cover the rest of a multi-piece outfit; see
            `AutoReplaceResult.unselected_mesh_pieces` for what's left.

    Returns:
        AutoReplaceResult with every intermediate artifact's path plus the
        final `DmmPackageResult`. `decimated` is `True` if the outfit had to
        be lossily simplified (beyond lossless welding) to fit the real PAC
        vertex-per-submesh limit.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    require_fitting_config(resolve_body_config(body_config_path))
    convert_dir = out_dir / "converted"
    conversion = convert(skyrim_mesh_path, body_config_path, convert_dir, deformer_name, atlas=atlas)
    outfit_obj_path, unselected_mesh_pieces = _select_outfit_obj_path(conversion, mesh_selector)
    if unselected_mesh_pieces:
        warnings.warn(
            f"This outfit has {len(unselected_mesh_pieces) + 1} separate piece(s); only "
            f"'{outfit_obj_path.name}' is being merged onto donor '{donor.entry_path}'. "
            f"The other {len(unselected_mesh_pieces)} piece(s) were converted but NOT packaged: "
            f"{unselected_mesh_pieces}. Run auto_replace_from_skyrim again with a matching "
            "mesh_selector and a donor for that piece's slot to cover them.",
            RuntimeWarning,
            stacklevel=2,
        )
    cf = cfb.load_crimsonforge_modules(crimsonforge_home)
    vfs = cfb.open_vfs(cf, packages_path)
    (
        asset,
        sidecar_files,
        outfit_vertex_count_before,
        outfit_vertex_count_after,
        decimated,
        merged_obj_path,
        rebuilt_pac_path,
    ) = _process_one_piece(cf, vfs, outfit_obj_path, donor, out_dir, "piece", shrink_factor, decimation_agg)

    package = build_dmm_package(
        [asset],
        out_dir / "dmm_package",
        title=title,
        author=author,
        version=version,
        game_build=game_build,
        description=description or f"sky2cd auto-conversion, replacing {donor.display_name}.",
        extra_files=sidecar_files,
    )

    return AutoReplaceResult(
        conversion_report_path=conversion.report_path,
        merged_obj_path=merged_obj_path,
        rebuilt_pac_path=rebuilt_pac_path,
        dmm_package=package,
        outfit_vertex_count_before=outfit_vertex_count_before,
        outfit_vertex_count_after=outfit_vertex_count_after,
        decimated=decimated,
        sidecar_file_paths=sorted(sidecar_files.keys()),
        selected_mesh_piece=str(outfit_obj_path),
        unselected_mesh_pieces=unselected_mesh_pieces,
    )


def auto_replace_batch_from_skyrim(
    skyrim_mesh_path: str | Path,
    body_config_path: str | Path | dict,
    pieces: list[PieceReplacement] | None,
    packages_path: str | Path,
    crimsonforge_home: str | Path,
    out_dir: str | Path,
    *,
    title: str,
    author: str = "sky2cd",
    version: str = "1.0.0",
    game_build: str = "",
    description: str = "",
    deformer_name: str = "idw",
    shrink_factor: float = 0.02,
    decimation_agg: float = 7.0,
    atlas: bool = False,
    max_workers: int | None = None,
) -> BatchAutoReplaceResult:
    """Convert every requested piece of a multi-piece Skyrim outfit and
    package all of them together into **one** droppable DMM mod folder.

    **Why this exists:** `auto_replace_from_skyrim` handles one piece per
    run (real, confirmed multi-piece outfits like Sherwood Huntress --
    Boots/Dress/Gloves/Hood as four separate meshes -- need 4 separate runs,
    each producing its own mod folder). This function does the whole outfit
    in one call: `sky2cd.pipeline.convert` runs exactly once (not once per
    piece), then each `(mesh_selector, donor)` pair in `pieces` is merged
    onto its own donor and rebuilt, and **all** resulting `.pac` files are
    combined into a single `build_dmm_package(...)` call -- one mod folder,
    with one `character/<item>.pac` per piece, that a single DMM install
    step enables as the complete outfit.

    Args:
        skyrim_mesh_path: Skyrim outfit mesh or archive (same as
            `auto_replace_from_skyrim`).
        body_config_path: body preset name/path/dict (e.g. `"fem_kliff"`).
        pieces: one `PieceReplacement(mesh_selector, donor)` per piece to
            include. Each `mesh_selector` is matched the same way as
            `auto_replace_from_skyrim`'s `mesh_selector` argument. Any piece
            the archive contains that no `mesh_selector` matches is reported
            in the returned `unmatched_mesh_pieces` (and a warning is
            raised) rather than silently dropped. Pass `None` to skip manual
            mapping entirely: each piece's slot is guessed from its filename
            (`sky2cd.donor_auto_select.guess_slot_from_path`) and matched
            against `sky2cd.donor_catalog`'s built-in donors automatically.
            A piece auto-resolves only when exactly one catalog donor
            matches its guessed slot; pieces with zero matches show up in
            `unmatched_mesh_pieces`, and pieces with more than one candidate
            show up in the returned `ambiguous_mesh_pieces` (both left
            unconverted) -- pass an explicit `pieces` list (even a partial
            one covering just the ambiguous/unmatched pieces isn't
            supported in one call today; re-run with all pieces explicit)
            to resolve those.
        packages_path, crimsonforge_home: same as `auto_replace_from_skyrim`.
        out_dir: working directory for intermediate + final output.
        title, author, version, game_build, description: DMM package
            metadata for the single, combined package.
        deformer_name, shrink_factor, decimation_agg: same as
            `auto_replace_from_skyrim`, applied per piece.
        max_workers: `None` or `1` (default) processes pieces sequentially
            in this process, identical to the original behavior. Any other
            value runs pieces concurrently across up to that many OS
            processes via `concurrent.futures.ProcessPoolExecutor` (`-1`
            means "use all CPU cores", capped at `len(pieces)`) -- a real,
            confirmed speedup since CrimsonForge's own per-piece rebuild
            step (not sky2cd's Python code) is the dominant cost of a
            multi-piece conversion and each piece's donor merge + rebuild is
            fully independent of every other piece. Piece order in the
            returned `pieces` list is preserved regardless of completion
            order. If running from a frozen `.exe`, `multiprocessing.
            freeze_support()` must have already been called in the entry
            point (`sky2cd.cli.main`'s `__main__` guard does this).

    Returns:
        BatchAutoReplaceResult with one `PieceResult` per requested piece,
        the combined `DmmPackageResult`, and any leftover unmatched pieces.

    Raises:
        ValueError: if `pieces` is an explicit empty list, if any
            `mesh_selector` matches no piece in the outfit, if auto-
            selection (`pieces=None`) couldn't confidently resolve a donor
            for any piece at all, or if the outfit has only a single piece
            (no `meshes` list to select from) and more than one piece was
            requested.
    """
    if pieces is not None and not pieces:
        raise ValueError("pieces must not be empty -- nothing to convert")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    require_fitting_config(resolve_body_config(body_config_path))
    convert_dir = out_dir / "converted"
    conversion = convert(skyrim_mesh_path, body_config_path, convert_dir, deformer_name, atlas=atlas)
    meshes = conversion.report.get("meshes")
    if not meshes:
        if pieces is not None and len(pieces) > 1:
            raise ValueError(
                "This input has only a single mesh piece (no separate "
                "boots/gloves/hood/etc.), so a batch of multiple pieces "
                "isn't applicable -- use auto_replace_from_skyrim instead."
            )
        relative_paths = ["<single piece>"]
        piece_obj_paths = [Path(conversion.report["output_obj"])]
    else:
        relative_paths = [m["relative_path"] for m in meshes]
        piece_obj_paths = [Path(m["obj_path"]) for m in meshes]

    ambiguous_mesh_pieces: list[dict] = []
    if pieces is None:
        # Auto-select: guess a slot per piece from its filename, then
        # resolve it against the built-in donor catalog. Only pieces that
        # resolve to EXACTLY one candidate donor get auto-converted;
        # ambiguous/unmatched pieces are reported, not guessed further.
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
        if not pieces:
            detail = f" Ambiguous piece(s): {ambiguous_mesh_pieces}." if ambiguous_mesh_pieces else ""
            raise ValueError(
                "Auto-donor-selection could not confidently resolve a donor for any of the "
                f"{len(relative_paths)} piece(s) found in this outfit.{detail} Pass an explicit "
                "`pieces`/`--piece \"selector=donor_id\"` for each piece instead."
            )

    matched_indices: set[int] = set()
    piece_specs: list[tuple[PieceReplacement, int]] = []
    for piece in pieces:
        index = _match_piece_index(relative_paths, piece.mesh_selector)
        matched_indices.add(index)
        piece_specs.append((piece, index))

    unmatched_mesh_pieces = [rp for i, rp in enumerate(relative_paths) if i not in matched_indices]

    piece_jobs: list[tuple[Path, DonorEntry, str]] = [
        (piece_obj_paths[mesh_index], piece.donor, f"{piece_index:02d}_{_sanitize_piece_tag(piece.mesh_selector)}")
        for piece_index, (piece, mesh_index) in enumerate(piece_specs)
    ]

    if max_workers in (None, 1) or len(piece_jobs) <= 1:
        # Sequential path (unchanged from before parallelism was added):
        # load CrimsonForge + open the VFS once, reused for every piece.
        cf = cfb.load_crimsonforge_modules(crimsonforge_home)
        vfs = cfb.open_vfs(cf, packages_path)
        piece_process_results = [
            _process_one_piece(cf, vfs, obj_path, donor, out_dir, piece_tag, shrink_factor, decimation_agg)
            for obj_path, donor, piece_tag in piece_jobs
        ]
    else:
        # Real perf win (see `_process_one_piece_worker`'s docstring):
        # CrimsonForge's own per-piece rebuild dominates real wall time, and
        # each piece is fully independent, so run them across processes.
        # `executor.map` preserves input order in its results regardless of
        # completion order, which matters here (piece_results below is
        # zipped back against `piece_specs` positionally).
        worker_count = os.cpu_count() or 1 if max_workers == -1 else max_workers
        worker_count = max(1, min(worker_count, len(piece_jobs)))
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            piece_process_results = list(
                executor.map(
                    _process_one_piece_worker,
                    [crimsonforge_home] * len(piece_jobs),
                    [packages_path] * len(piece_jobs),
                    [obj_path for obj_path, _donor, _tag in piece_jobs],
                    [donor for _obj_path, donor, _tag in piece_jobs],
                    [out_dir] * len(piece_jobs),
                    [piece_tag for _obj_path, _donor, piece_tag in piece_jobs],
                    [shrink_factor] * len(piece_jobs),
                    [decimation_agg] * len(piece_jobs),
                )
            )

    assets: list[DmmAsset] = []
    combined_sidecar_files: dict[str, bytes] = {}
    piece_results: list[PieceResult] = []
    for piece_index, ((piece, mesh_index), process_result) in enumerate(zip(piece_specs, piece_process_results)):
        outfit_obj_path = piece_obj_paths[mesh_index]
        (
            asset,
            sidecar_files,
            vertex_count_before,
            vertex_count_after,
            decimated,
            merged_obj_path,
            rebuilt_pac_path,
        ) = process_result
        assets.append(asset)
        combined_sidecar_files.update(sidecar_files)
        piece_results.append(
            PieceResult(
                mesh_selector=piece.mesh_selector,
                selected_mesh_piece=str(outfit_obj_path),
                donor_entry_path=piece.donor.entry_path,
                merged_obj_path=merged_obj_path,
                rebuilt_pac_path=rebuilt_pac_path,
                outfit_vertex_count_before=vertex_count_before,
                outfit_vertex_count_after=vertex_count_after,
                decimated=decimated,
            )
        )

    if unmatched_mesh_pieces:
        warnings.warn(
            f"This outfit has {len(relative_paths)} piece(s); {len(unmatched_mesh_pieces)} "
            f"were converted but NOT covered by any `pieces` entry (no donor assigned): "
            f"{unmatched_mesh_pieces}. Add a PieceReplacement/--piece for each to cover the "
            "whole outfit.",
            RuntimeWarning,
            stacklevel=2,
        )

    package = build_dmm_package(
        assets,
        out_dir / "dmm_package",
        title=title,
        author=author,
        version=version,
        game_build=game_build,
        description=description or f"sky2cd auto-conversion, replacing {len(assets)} item(s).",
        extra_files=combined_sidecar_files,
    )

    return BatchAutoReplaceResult(
        conversion_report_path=conversion.report_path,
        dmm_package=package,
        pieces=piece_results,
        unmatched_mesh_pieces=unmatched_mesh_pieces,
        sidecar_file_paths=sorted(combined_sidecar_files.keys()),
        ambiguous_mesh_pieces=ambiguous_mesh_pieces,
    )
