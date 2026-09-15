from __future__ import annotations

import argparse
import multiprocessing
import sys
from pathlib import Path

from sky2cd.pipeline import convert, pretty_report
from sky2cd.presets import build_custom_preset, list_presets

WELCOME = """\
sky2cd - Blender-first preparation tools for artist-assisted outfit work

sky2cd prepares Skyrim outfit geometry for inspection and manual work in Blender. Its
primary output is a preview/mockup, not a fitted, rigged, tested, or game-ready outfit.
The artist remains responsible for fit, clipping, materials, native rig/weights,
rebuild/export, and in-game/animation testing.

Donor lookup/export and DMM packaging are optional advanced utilities for work the
artist has already rebuilt and validated; they do not certify a usable in-game result.

No command was given. Start with the Blender-first workflow:

  sky2cd blender-handoff --input <outfit.zip> --out <dir>
      # writes source preview OBJ(s), metadata, and an import_script.py for Blender.
  # Open <dir>/handoff/import_script.py, then inspect, fit, clip, weight-paint,
  # rig, and validate manually. A donor can be added later when it helps.
  sky2cd package-dmm --strict --pac <artist-rebuilt.pac> --entry-path <game/relative/path.pac> \\
      --sidecar "game/relative/path.pac_xml=<local .pac_xml>" --title <name> --out <dir>
      # structural packaging checks only; this does not validate fit, rig, or gameplay.

Other commands:

  sky2cd convert <outfit.nif / outfit.7z / outfit.zip / .meshir.json> [--body-config <preset or config.json>] --deformer idw --out <dir>
  sky2cd presets
  sky2cd build-preset --source-body <base.nif> --target-body <reshaped.nif> --name <name> --out <dir>
  sky2cd merge --donor <donor.obj> --outfit <outfit.obj> --out <merged.obj>
  sky2cd package-dmm --pac <merged.pac> --entry-path <game/relative/path.pac> --title <name> --out <dir>
  sky2cd donors [--verify --packages-path <path> --crimsonforge-home <path>] [--ingame-names]
  sky2cd donors --suggest <piece-name-or-file> [--packages-path <path> --crimsonforge-home <path>]
  sky2cd auto-replace --input <outfit.nif> --donor-id <catalog-id> --packages-path <path> \\
      --crimsonforge-home <path> --title <name> --out <dir>
  sky2cd auto-replace-all --input <outfit.zip> --piece "boots=some_donor_id" --piece "gloves=proxima_ref_hands" \\
      --packages-path <path> --crimsonforge-home <path> --title <name> --out <dir>
  sky2cd auto-replace-all --input <outfit.zip> --packages-path <path> --crimsonforge-home <path> \\
      --title <name> --out <dir>   # omit --piece entirely to auto-select a donor per piece
  sky2cd report <run-report.json>

auto-replace/auto-replace-all are advanced experimental commands for a custom,
artist-validated body-fit config. Without one they refuse to produce a DMM package.

Built-in body presets:
  - fem_kliff (Default: geometry/alignment preview only, NOT a Fem Kliff fit)
  - cd_vanilla_female (Geometry/alignment preview only)

Automatic PAC/DMM packaging requires a suitable custom body-reference config.

Run 'sky2cd --help' for full option details.
"""


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _load_body_mesh(path: Path):
    """Load a body reference mesh from .nif or .meshir.json for build-preset."""
    from sky2cd.meshir import load_meshir

    if not path.is_file():
        raise FileNotFoundError(f"Body mesh file not found: {path}")
    suffix = "".join(path.suffixes).lower()
    if suffix.endswith(".meshir.json") or path.suffix.lower() == ".json":
        return load_meshir(path)
    if path.suffix.lower() == ".nif":
        from sky2cd.importers.nif_importer import import_nif

        return import_nif(path)
    raise ValueError(f"Unsupported body mesh format '{path.suffix}' (expected .nif or .meshir.json)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sky2cd",
        description="Blender-first preparation tools for artist-assisted outfit work (preview/mockup output, not game-ready conversion)",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    convert_parser = subcommands.add_parser(
        "convert",
        help="Create Blender-preview geometry and a diagnostic PAC from a NIF, MeshIR, or archive (not game-ready)",
    )
    convert_parser.add_argument("input", type=Path)
    convert_parser.add_argument(
        "--body-config",
        default="fem_kliff",
        type=str,
        help="Custom body-config JSON or built-in geometry-only preview (default: 'fem_kliff')",
    )
    convert_parser.add_argument("--deformer", default="idw", choices=["idw", "rigid-mls", "bsw"])
    convert_parser.add_argument("--atlas", action="store_true", help="Auto-pack multi-submesh UVs and textures into a single unified atlas (skip Blender manual baking)")
    convert_parser.add_argument("--out", required=True, type=Path)

    subcommands.add_parser("presets", help="List all available built-in body presets")

    build_preset_parser = subcommands.add_parser(
        "build-preset",
        help="Bake a reusable body-config preset from a source/target body pair (one-time setup)",
    )
    build_preset_parser.add_argument("--source-body", required=True, type=Path, help=".nif or .meshir.json reference body (e.g. stock CBBE/3BA)")
    build_preset_parser.add_argument("--target-body", required=True, type=Path, help=".nif or .meshir.json reshaped body, SAME topology as --source-body")
    build_preset_parser.add_argument("--name", required=True, type=str, help="Preset name; used for output filenames")
    build_preset_parser.add_argument("--out", required=True, type=Path, help="Directory to write the preset config + body meshes into")
    build_preset_parser.add_argument("--scale", default=1.0, type=float)

    merge_parser = subcommands.add_parser(
        "merge",
        help="Advanced: merge outfit preview geometry onto a donor OBJ for manual review (not a fit, rig, or game-ready result)",
    )
    merge_parser.add_argument("--donor", required=True, type=Path, help="Donor item's .obj (e.g. exported from CrimsonForge)")
    merge_parser.add_argument("--outfit", required=True, type=Path, help="Converted outfit .obj (e.g. from 'sky2cd convert')")
    merge_parser.add_argument("--out", required=True, type=Path, help="Output merged .obj path")
    merge_parser.add_argument("--shrink", default=0.02, type=float, help="Donor shrink factor toward its bounding-box center (default 0.02)")
    merge_parser.add_argument("--submesh-strategy", default="nearest", choices=["nearest", "append"])

    report_parser = subcommands.add_parser("report", help="Pretty-print a conversion report")
    report_parser.add_argument("run_report", type=Path)

    package_parser = subcommands.add_parser(
        "package-dmm",
        help="Optional advanced: package an artist-rebuilt .pac as a DMM-compatible loose-file mod "
        "(verified against a real installed DMM: files/<game-relative-path> + manifest.json + modinfo.json, "
        "no in-place game archive patching required)",
    )
    package_parser.add_argument("--pac", required=True, type=Path, help="Merged/rebuilt .pac file to include")
    package_parser.add_argument(
        "--entry-path",
        required=True,
        type=str,
        help="Real game VFS-relative path this .pac replaces, forward slashes, "
        "no package-group prefix (e.g. 'character/cd_phw_00_lb_00_0182.pac')",
    )
    package_parser.add_argument("--package-group", default="", type=str, help="Real package-group folder name (e.g. '0009'), informational only")
    package_parser.add_argument("--title", required=True, type=str, help="Mod display title; also used as the output folder name")
    package_parser.add_argument("--author", default="sky2cd", type=str)
    package_parser.add_argument("--version", default="1.0.0", type=str)
    package_parser.add_argument("--description", default="", type=str)
    package_parser.add_argument("--game-build", default="", type=str, help="Informational game build string, e.g. 'v2.02.00'")
    package_parser.add_argument(
        "--sidecar",
        action="append",
        metavar="GAME_RELATIVE_PATH=LOCAL_FILE",
        help="An additional file to bundle alongside the .pac (e.g. its .pac_xml material sidecar "
        "or a texture), as 'character/foo.pac_xml=C:/path/to/local_file'. Repeat once per file. "
        "Required (a matching '<stem>.pac_xml') when --strict is set.",
    )
    package_parser.add_argument(
        "--strict",
        action="store_true",
        help="Run pre-flight validation before writing anything: require a matching .pac_xml "
        "sidecar (via --sidecar), and, if --crimsonforge-home is also given, verify the .pac "
        "parses via CrimsonForge itself. On success, also writes provenance.json (sha256 of "
        "every packaged file). This does NOT validate body fit, clipping, or animation -- only "
        "structural sanity and sidecar completeness. Default (no --strict) behavior is unchanged.",
    )
    package_parser.add_argument(
        "--crimsonforge-home",
        default=None,
        type=Path,
        help="Path to a CrimsonForge install's source root, used only with --strict to verify "
        "the .pac is parseable",
    )
    package_parser.add_argument("--out", required=True, type=Path, help="Directory to create the mod folder in")

    donors_parser = subcommands.add_parser(
        "donors",
        help="Optional: list the built-in donor catalog (metadata only, no game assets bundled), "
        "optionally verifying each entry against a real, live game install",
    )
    donors_parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify each catalog entry actually resolves against a real game install "
        "(requires --packages-path and --crimsonforge-home)",
    )
    donors_parser.add_argument("--packages-path", default=None, type=Path, help="Path to the game's packages/ directory (for live verification/recommendations)")
    donors_parser.add_argument("--crimsonforge-home", default=None, type=Path, help="Path to a CrimsonForge install's source root (for live verification/recommendations)")
    donors_parser.add_argument(
        "--ingame-names",
        action="store_true",
        help="Resolve and print each entry's real in-game display name next to its cryptic "
        "path (requires --packages-path and --crimsonforge-home; entries with no player-"
        "obtainable item record print '(no in-game item)')",
    )
    donors_parser.add_argument(
        "--suggest",
        metavar="PIECE",
        help="Recommend and rank donors for an outfit piece filename or supported mesh file. "
        "With game/tool paths, also checks live provenance, sidecars, names, and bounds compatibility. "
        "Recommendations are artist starting points, not fit/rig/game-ready guarantees.",
    )
    donors_parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Maximum recommendations to show with --suggest (default: 3)",
    )
    donors_parser.add_argument(
        "--suggest-out",
        type=Path,
        help="Write the same ranked recommendation payload to JSON for Blender/tooling/reference "
        "(requires --suggest)",
    )

    auto_parser = subcommands.add_parser(
        "auto-replace",
        help="Advanced experimental: package an artist-validated custom body-fit workflow; "
        "not an automatic wearable conversion or game-ready guarantee",
    )
    auto_parser.add_argument("--input", required=True, type=Path, help="Skyrim outfit .nif/.meshir.json/archive")
    auto_parser.add_argument("--body-config", default="fem_kliff", type=str, help="Custom body-fit config required; bundled preview presets are blocked")
    auto_parser.add_argument("--donor-id", required=True, type=str, help="Donor catalog id, see 'sky2cd donors'")
    auto_parser.add_argument("--packages-path", required=True, type=Path, help="Path to the real game's packages/ directory")
    auto_parser.add_argument("--crimsonforge-home", required=True, type=Path, help="Path to a CrimsonForge install's source root")
    auto_parser.add_argument("--title", required=True, type=str)
    auto_parser.add_argument("--author", default="sky2cd", type=str)
    auto_parser.add_argument("--version", default="1.0.0", type=str)
    auto_parser.add_argument("--description", default="", type=str)
    auto_parser.add_argument("--game-build", default="", type=str)
    auto_parser.add_argument("--deformer", default="idw", choices=["idw", "bsw", "rigid_mls"])
    auto_parser.add_argument(
        "--decimation-agg",
        default=7.0,
        type=float,
        help="fast_simplification aggressiveness (0-10) used only if the outfit needs lossy "
        "simplification to fit the real PAC 65535-vertex-per-submesh limit; higher preserves "
        "more detail but decimates slower (default: 7.0)",
    )
    auto_parser.add_argument(
        "--mesh-selector",
        default=None,
        type=str,
        help="If the input archive has multiple separate pieces (e.g. boots/gloves/hood/dress), "
        "a case-insensitive substring to pick which one to merge onto --donor-id (e.g. 'gloves'). "
        "Defaults to the first piece found. Run auto-replace again with a different "
        "--mesh-selector and a --donor-id matching that piece's slot to cover the rest of a "
        "multi-piece outfit -- the command prints a warning listing what else was found.",
    )
    auto_parser.add_argument("--atlas", action="store_true", help="Auto-pack multi-submesh UVs and textures into a single unified atlas")
    auto_parser.add_argument("--out", required=True, type=Path, help="Working/output directory")

    auto_all_parser = subcommands.add_parser(
        "auto-replace-all",
        help="Advanced experimental multi-piece packaging for artist-validated custom body fits; "
        "not an automatic wearable conversion or game-ready guarantee",
    )
    auto_all_parser.add_argument("--input", required=True, type=Path, help="Skyrim outfit archive (multiple pieces)")
    auto_all_parser.add_argument("--body-config", default="fem_kliff", type=str, help="Custom body-fit config required; bundled preview presets are blocked")
    auto_all_parser.add_argument(
        "--piece",
        action="append",
        required=False,
        metavar="MESH_SELECTOR=DONOR_ID",
        help="One piece to convert, as 'mesh_selector=donor_id' (e.g. 'gloves=proxima_ref_hands'). "
        "mesh_selector is matched case-insensitively as a substring against each piece's filename "
        "found in the archive. Repeat --piece once per piece to cover the whole outfit (e.g. 4 "
        "times for a boots/dress/gloves/hood outfit); any piece left uncovered is reported, not "
        "silently dropped. Omit --piece entirely to auto-select a donor for every piece instead: "
        "each piece's slot is guessed from its filename and matched against the built-in donor "
        "catalog; pieces with zero or more than one matching donor are reported (not converted) "
        "so you can cover just those with an explicit --piece.",
    )
    auto_all_parser.add_argument("--packages-path", required=True, type=Path, help="Path to the real game's packages/ directory")
    auto_all_parser.add_argument("--crimsonforge-home", required=True, type=Path, help="Path to a CrimsonForge install's source root")
    auto_all_parser.add_argument("--title", required=True, type=str)
    auto_all_parser.add_argument("--author", default="sky2cd", type=str)
    auto_all_parser.add_argument("--version", default="1.0.0", type=str)
    auto_all_parser.add_argument("--description", default="", type=str)
    auto_all_parser.add_argument("--game-build", default="", type=str)
    auto_all_parser.add_argument("--deformer", default="idw", choices=["idw", "bsw", "rigid_mls"])
    auto_all_parser.add_argument(
        "--decimation-agg",
        default=7.0,
        type=float,
        help="fast_simplification aggressiveness (0-10), applied per piece if it needs lossy "
        "simplification to fit the real PAC 65535-vertex-per-submesh limit (default: 7.0)",
    )
    auto_all_parser.add_argument("--atlas", action="store_true", help="Auto-pack multi-submesh UVs and textures into a single unified atlas")
    auto_all_parser.add_argument(
        "--max-workers",
        default=1,
        type=int,
        metavar="N",
        help="Process pieces in parallel across up to N OS processes via ProcessPoolExecutor "
        "instead of one at a time (default: 1, sequential -- identical to previous behavior). "
        "Use -1 to use all CPU cores. Real, confirmed speedup: CrimsonForge's own per-piece "
        "rebuild step (not sky2cd's Python code) is the dominant cost of a multi-piece "
        "conversion (roughly 1.5-4 minutes per piece observed live), and each piece's donor "
        "merge + rebuild is fully independent, so this can turn N sequential rebuilds into "
        "roughly one rebuild's wall time (bounded by core count).",
    )
    auto_all_parser.add_argument("--out", required=True, type=Path, help="Working/output directory")

    handoff_parser = subcommands.add_parser(
        "blender-handoff",
        help="Recommended: create a Blender import bundle for manual artist work. Donors are optional; "
        "output is a preview/mockup, not a fitted, rigged, or game-ready asset.",
    )
    handoff_parser.add_argument("--input", required=True, type=Path, help="Skyrim outfit .nif/.meshir.json/archive")
    handoff_parser.add_argument(
        "--body-config",
        default="fem_kliff",
        type=str,
        help="Body preset/config used only for geometry/axis conversion (default: 'fem_kliff'); "
        "a validated custom body-fit config is NOT required for a handoff",
    )
    handoff_parser.add_argument(
        "--piece",
        action="append",
        required=False,
        metavar="MESH_SELECTOR=DONOR_ID",
        help="One piece to hand off, as 'mesh_selector=donor_id' (see 'sky2cd donors' for ids). "
        "Repeat once per piece. Omit entirely to auto-select a donor per piece the same way "
        "'auto-replace-all' does (ambiguous/unmatched pieces are reported, not guessed).",
    )
    handoff_parser.add_argument(
        "--packages-path",
        default=None,
        type=Path,
        help="Path to the real game's packages/ directory (optional: omit for a source-only, "
        "donor-less handoff)",
    )
    handoff_parser.add_argument(
        "--crimsonforge-home",
        default=None,
        type=Path,
        help="Path to a CrimsonForge install's source root (optional, see --packages-path)",
    )
    handoff_parser.add_argument("--deformer", default="idw", choices=["idw", "rigid-mls", "bsw"])
    handoff_parser.add_argument("--atlas", action="store_true", help="Auto-pack multi-submesh UVs and textures into a single unified atlas")
    handoff_parser.add_argument(
        "--no-ingame-names",
        action="store_true",
        help="Skip resolving each donor's real in-game display name even if --packages-path/"
        "--crimsonforge-home are given",
    )
    handoff_parser.add_argument("--out", required=True, type=Path, help="Directory to write the handoff bundle into")

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        # Launched with no arguments -- most likely a double-click on the frozen
        # exe from Explorer. Explain usage instead of the window vanishing
        # instantly, and keep the console open long enough to read it.
        print(WELCOME)
        build_parser().print_help()
        if _is_frozen() and sys.stdin is not None and sys.stdin.isatty():
            try:
                input("\nPress Enter to exit...")
            except EOFError:
                pass
        return 1

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "convert":
        try:
            result = convert(args.input, args.body_config, args.out, args.deformer, atlas=args.atlas)
        except (ImportError, ValueError, FileNotFoundError, NotImplementedError) as exc:
            parser.exit(1, f"sky2cd: error: {exc}\n")
        print(f"Wrote {result.pac_path}")
        print(f"Wrote {result.report_path}")
        return 0
    if args.command == "presets":
        presets = list_presets()
        print("Available body presets:")
        for key, name in presets.items():
            print(f"  - {key}: {name}")
        return 0
    if args.command == "build-preset":
        try:
            source_body = _load_body_mesh(args.source_body)
            target_body = _load_body_mesh(args.target_body)
            config_path = build_custom_preset(
                source_body, target_body, args.name, args.out, scale=args.scale
            )
        except (ImportError, ValueError, FileNotFoundError) as exc:
            parser.exit(1, f"sky2cd: error: {exc}\n")
        print(f"Wrote {config_path}")
        print(f"Use it with: sky2cd convert <outfit> --body-config {config_path}")
        return 0
    if args.command == "merge":
        try:
            from sky2cd.donor_merge import merge_onto_donor
            from sky2cd.exporters.obj_exporter import write_obj
            from sky2cd.importers.obj_importer import read_obj

            donor = read_obj(args.donor)
            outfit = read_obj(args.outfit)
            merged = merge_onto_donor(
                donor, outfit, shrink_factor=args.shrink, submesh_strategy=args.submesh_strategy
            )
            out_path = write_obj(merged, args.out, axis_convert=False)
        except (ImportError, ValueError, FileNotFoundError) as exc:
            parser.exit(1, f"sky2cd: error: {exc}\n")
        print(f"Wrote {out_path}")
        print(
            "Wrote a geometrically-merged .obj.\n"
            "VERIFIED against the real game (v2.02.00) + CrimsonForge v1.26.0 source: when "
            "you import this .obj back over the donor's ORIGINAL exported .obj (same file, "
            "same source_path/source_format header) and rebuild with CrimsonForge's "
            "build_pac(), new vertices automatically inherit bone weights from the nearest "
            "original donor vertex -- no .cfmeta.json sidecar or Blender weight-painting is "
            "required for this to work mechanically. Coverage still depends on the donor's "
            "own weight density (some donor vertices are themselves unweighted/rigid, so "
            "new geometry landing there also stays unweighted -- the same regions a manual "
            "weight-paint pass would need to fix anyway). See README.md for the full "
            "explanation and how to reproduce this test."
        )
        return 0
    if args.command == "report":
        print(pretty_report(args.run_report))
        return 0
    if args.command == "package-dmm":
        try:
            from sky2cd.dmm_package import DmmAsset, build_dmm_package

            pac_bytes = args.pac.read_bytes()
            asset = DmmAsset(
                entry_path=args.entry_path,
                pac_bytes=pac_bytes,
                package_group=args.package_group,
                source_obj_path=str(args.pac),
            )
            extra_files: dict[str, bytes] = {}
            for spec in args.sidecar or []:
                if "=" not in spec:
                    raise ValueError(f"--sidecar must be 'game/relative/path=local_file', got: {spec!r}")
                rel_path, local_path = spec.split("=", 1)
                extra_files[rel_path] = Path(local_path).read_bytes()
            cf = None
            if args.strict and args.crimsonforge_home:
                from sky2cd import crimsonforge_bridge as cfb

                cf = cfb.load_crimsonforge_modules(args.crimsonforge_home)
            result = build_dmm_package(
                [asset],
                args.out,
                title=args.title,
                author=args.author,
                version=args.version,
                description=args.description,
                game_build=args.game_build,
                extra_files=extra_files,
                strict=args.strict,
                cf=cf,
            )
        except (ImportError, ValueError, FileNotFoundError) as exc:
            parser.exit(1, f"sky2cd: error: {exc}\n")
        print(f"Wrote {result.mod_dir}")
        print(f"Wrote {result.manifest_path}")
        print(f"Wrote {result.modinfo_path}")
        for p in result.file_paths:
            print(f"Wrote {p}")
        if result.provenance_path:
            print(f"Wrote {result.provenance_path}")
        print(
            "Drop this folder into your DMM 'mods' directory and enable it as a "
            "browser mod -- no in-place game archive patching needed."
        )
        if args.strict:
            print(
                "STRICT MODE: verified required sidecar presence"
                + (" and CrimsonForge .pac readability" if cf is not None else "")
                + ". This does NOT validate body fit, clipping, weight/rig transfer, or "
                "in-game/animation correctness -- that is still the artist's responsibility."
            )
        return 0
    if args.command == "donors":
        from sky2cd.donor_catalog import list_catalog

        entries = list_catalog()
        if args.suggest:
            try:
                from sky2cd.donor_recommendation import (
                    format_recommendations,
                    gather_live_evidence,
                    rank_donors,
                    write_recommendation_json,
                )

                recommendations = rank_donors(args.suggest, catalog=entries)
                has_packages = bool(args.packages_path)
                has_crimsonforge = bool(args.crimsonforge_home)
                if has_packages != has_crimsonforge:
                    raise ValueError(
                        "--suggest requires both --packages-path and --crimsonforge-home "
                        "when either live-install path is supplied"
                    )
                if has_packages:
                    from sky2cd import crimsonforge_bridge as cfb

                    cf = cfb.load_crimsonforge_modules(args.crimsonforge_home)
                    vfs = cfb.open_vfs(cf, args.packages_path)
                    candidate_entries = [recommendation.entry for recommendation in recommendations]
                    evidence = gather_live_evidence(args.suggest, candidate_entries, cf=cf, vfs=vfs)
                    recommendations = rank_donors(
                        args.suggest,
                        catalog=candidate_entries,
                        evidence_by_id=evidence,
                    )
                print(format_recommendations(args.suggest, recommendations, limit=args.limit))
                if args.suggest_out:
                    output_path = write_recommendation_json(
                        args.suggest_out,
                        args.suggest,
                        recommendations,
                        limit=args.limit,
                    )
                    print(f"Wrote {output_path}")
            except (ImportError, ValueError, FileNotFoundError, RuntimeError) as exc:
                parser.exit(1, f"sky2cd: error: {exc}\n")
            return 0
        if args.suggest_out:
            parser.exit(1, "sky2cd: error: --suggest-out requires --suggest\n")

        name_resolver = None
        if args.ingame_names:
            if not args.packages_path or not args.crimsonforge_home:
                parser.exit(1, "sky2cd: error: --ingame-names requires --packages-path and --crimsonforge-home\n")
            try:
                from sky2cd import crimsonforge_bridge as cfb
                from sky2cd.crimsonforge_bridge import CrimsonForgeNotFoundError

                cf = cfb.load_crimsonforge_modules(args.crimsonforge_home)
                vfs = cfb.open_vfs(cf, args.packages_path)
                name_resolver = cfb.build_item_name_resolver(cf, vfs)
            except (ImportError, ValueError, FileNotFoundError, CrimsonForgeNotFoundError, StopIteration) as exc:
                parser.exit(1, f"sky2cd: error: {exc}\n")
        if not args.verify:
            for entry in entries:
                line = (f"{entry.id}\t{entry.display_name}\t[{entry.slot}]\t{entry.entry_path}\t"
                        f"physics={entry.physics_quality}\tdyeable={entry.dyeable}")
                if name_resolver is not None:
                    ingame_name = name_resolver.resolve(entry.entry_path) or "(no in-game item)"
                    line += f"\tingame_name={ingame_name}"
                print(line)
            print(f"\n{len(entries)} catalog entries. Pass --verify --packages-path <dir> "
                  "--crimsonforge-home <dir> to check them against a real, live game install, "
                  "or add --ingame-names to also show each donor's real in-game item name.")
            return 0
        if not args.packages_path or not args.crimsonforge_home:
            parser.exit(1, "sky2cd: error: --verify requires --packages-path and --crimsonforge-home\n")
        try:
            from sky2cd import crimsonforge_bridge as cfb
            from sky2cd.crimsonforge_bridge import CrimsonForgeNotFoundError
            from sky2cd.donor_catalog import verify_against_install

            cf = cfb.load_crimsonforge_modules(args.crimsonforge_home)
            vfs = cfb.open_vfs(cf, args.packages_path)
            results = verify_against_install(vfs, entries)
            if name_resolver is None and args.ingame_names:
                name_resolver = cfb.build_item_name_resolver(cf, vfs)
        except (ImportError, ValueError, FileNotFoundError, CrimsonForgeNotFoundError) as exc:
            parser.exit(1, f"sky2cd: error: {exc}\n")
        for result in results:
            status = f"FOUND (group {result.resolved_package_group})" if result.found else f"MISSING: {result.error}"
            line = f"{result.entry.id}\t{result.entry.display_name}\t{status}"
            if name_resolver is not None:
                ingame_name = name_resolver.resolve(result.entry.entry_path) or "(no in-game item)"
                line += f"\tingame_name={ingame_name}"
            print(line)
        return 0
    if args.command == "auto-replace":
        try:
            from sky2cd.auto_replace import auto_replace_from_skyrim
            from sky2cd.donor_catalog import get_entry

            donor = get_entry(args.donor_id)
            result = auto_replace_from_skyrim(
                args.input,
                args.body_config,
                donor,
                args.packages_path,
                args.crimsonforge_home,
                args.out,
                title=args.title,
                author=args.author,
                version=args.version,
                game_build=args.game_build,
                description=args.description,
                deformer_name=args.deformer,
                decimation_agg=args.decimation_agg,
                mesh_selector=args.mesh_selector,
                atlas=args.atlas,
            )
        except (ImportError, ValueError, FileNotFoundError, KeyError) as exc:
            parser.exit(1, f"sky2cd: error: {exc}\n")
        print(f"Wrote {result.conversion_report_path}")
        print(f"Wrote {result.merged_obj_path}")
        print(f"Wrote {result.rebuilt_pac_path}")
        print(f"Wrote {result.dmm_package.mod_dir}")
        print(f"Included {len(result.sidecar_file_paths)} real sidecar file(s) (.pac_xml + textures)")
        if result.decimated:
            print(
                f"Outfit was simplified to fit the real PAC vertex limit: "
                f"{result.outfit_vertex_count_before} -> {result.outfit_vertex_count_after} vertices."
            )
        print(
            f"Replaces: {donor.display_name} ({donor.entry_path}).\n"
            "Drop the DMM package folder into your DMM 'mods' directory and enable it."
        )
        if result.unselected_mesh_pieces:
            print(
                f"NOTE: this outfit has {len(result.unselected_mesh_pieces) + 1} separate piece(s); "
                f"only '{Path(result.selected_mesh_piece).name}' was merged/packaged. "
                f"NOT included: {result.unselected_mesh_pieces}. Re-run with --mesh-selector and a "
                "matching --donor-id to cover the rest."
            )
        return 0
    if args.command == "auto-replace-all":
        try:
            from sky2cd.auto_replace import PieceReplacement, auto_replace_batch_from_skyrim
            from sky2cd.donor_catalog import get_entry

            if args.piece:
                pieces = []
                for spec in args.piece:
                    if "=" not in spec:
                        raise ValueError(f"--piece must be 'mesh_selector=donor_id', got: {spec!r}")
                    selector, donor_id = spec.split("=", 1)
                    pieces.append(PieceReplacement(mesh_selector=selector, donor=get_entry(donor_id)))
            else:
                # No --piece flags at all: auto-select a donor per piece by
                # guessing its slot from its filename (see
                # sky2cd.donor_auto_select). Ambiguous/unmatched pieces are
                # reported after the run, not guessed further.
                pieces = None

            result = auto_replace_batch_from_skyrim(
                args.input,
                args.body_config,
                pieces,
                args.packages_path,
                args.crimsonforge_home,
                args.out,
                title=args.title,
                author=args.author,
                version=args.version,
                game_build=args.game_build,
                description=args.description,
                deformer_name=args.deformer,
                decimation_agg=args.decimation_agg,
                atlas=args.atlas,
                max_workers=args.max_workers,
            )
        except (ImportError, ValueError, FileNotFoundError, KeyError) as exc:
            parser.exit(1, f"sky2cd: error: {exc}\n")
        print(f"Wrote {result.conversion_report_path}")
        if pieces is None:
            print("No --piece flags given: auto-selected a donor per piece from the built-in catalog.")
        for piece in result.pieces:
            note = " (simplified to fit PAC vertex limit)" if piece.decimated else ""
            print(f"  {piece.mesh_selector} -> {piece.donor_entry_path}: wrote {piece.rebuilt_pac_path}{note}")
        print(f"Wrote {result.dmm_package.mod_dir}")
        print(f"Included {len(result.sidecar_file_paths)} real sidecar file(s) (.pac_xml + textures) across all pieces")
        print(
            f"Packaged {len(result.pieces)} piece(s) into one DMM mod.\n"
            "Drop the DMM package folder into your DMM 'mods' directory and enable it."
        )
        if result.ambiguous_mesh_pieces:
            print(
                f"NOTE: {len(result.ambiguous_mesh_pieces)} piece(s) had more than one matching catalog "
                "donor, so none was auto-picked -- choose one and cover it with an explicit --piece:"
            )
            for entry in result.ambiguous_mesh_pieces:
                print(
                    f"  {entry['relative_path']} (guessed slot: {entry['guessed_slot']}): "
                    f"candidates = {entry['candidate_donor_ids']}"
                )
        if result.unmatched_mesh_pieces:
            print(
                f"NOTE: {len(result.unmatched_mesh_pieces)} piece(s) of this outfit were NOT covered "
                f"by any --piece: {result.unmatched_mesh_pieces}. Add a --piece for each to include "
                "them (e.g. --piece \"hood=some_donor_id\")."
            )
        return 0
    if args.command == "blender-handoff":
        try:
            from sky2cd.auto_replace import PieceReplacement
            from sky2cd.blender_handoff import build_blender_handoff
            from sky2cd.donor_catalog import get_entry

            if args.piece:
                pieces = []
                for spec in args.piece:
                    if "=" not in spec:
                        raise ValueError(f"--piece must be 'mesh_selector=donor_id', got: {spec!r}")
                    selector, donor_id = spec.split("=", 1)
                    pieces.append(PieceReplacement(mesh_selector=selector, donor=get_entry(donor_id)))
            else:
                pieces = None

            result = build_blender_handoff(
                args.input,
                args.body_config,
                pieces,
                args.packages_path,
                args.crimsonforge_home,
                args.out,
                deformer_name=args.deformer,
                atlas=args.atlas,
                resolve_ingame_names=not args.no_ingame_names,
            )
        except (ImportError, ValueError, FileNotFoundError, KeyError) as exc:
            parser.exit(1, f"sky2cd: error: {exc}\n")
        print(f"Wrote {result.conversion_report_path}")
        for warning in result.warnings:
            print(f"NOTE: {warning}")
        for piece in result.pieces:
            print(f"Piece '{piece.mesh_selector}': wrote {piece.metadata_path}")
            print(f"  source OBJ: {piece.source_obj_path}")
            if piece.donor_suggestion_path is not None:
                print(f"  donor suggestion JSON: {piece.donor_suggestion_path}")
            if piece.donor is not None:
                if piece.donor.obj_path is not None:
                    print(f"  donor OBJ ({piece.donor.entry_path}): {piece.donor.obj_path}")
                    print(f"  donor sidecars: {len(piece.donor.sidecar_paths)} file(s)")
                    if piece.donor.ingame_display_name:
                        print(f"  donor in-game name: {piece.donor.ingame_display_name}")
                elif piece.donor.error:
                    print(f"  WARNING: donor '{piece.donor.entry_path}' not exported: {piece.donor.error}")
        print(f"Wrote {result.import_script_path}")
        if result.ambiguous_mesh_pieces:
            print(
                f"NOTE: {len(result.ambiguous_mesh_pieces)} piece(s) had more than one matching catalog "
                "donor, so none was auto-picked -- choose one and cover it with an explicit --piece:"
            )
            for entry in result.ambiguous_mesh_pieces:
                print(
                    f"  {entry['relative_path']} (guessed slot: {entry['guessed_slot']}): "
                    f"candidates = {entry['candidate_donor_ids']}"
                )
        if result.unmatched_mesh_pieces:
            print(
                f"NOTE: {len(result.unmatched_mesh_pieces)} piece(s) of this outfit were NOT handed off: "
                f"{result.unmatched_mesh_pieces}. Add a --piece for each to include them."
            )
        print(
            "This is an artist handoff, NOT a finished conversion or mod: open the generated "
            "import_script.py in Blender (Scripting tab -> Run Script) to review source + donor "
            "meshes side by side. No body fitting, weight/rig transfer, clipping fixes, or "
            "material work has been done -- that's the artist's job, followed by "
            "'sky2cd package-dmm --strict' once a rebuilt .pac is ready."
        )
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    # Real requirement for `auto-replace-all --max-workers` in the frozen
    # PyInstaller `.exe`: multiprocessing.Process on Windows re-executes the
    # frozen executable to bootstrap each child, and without freeze_support()
    # (called here, before any other code, per the standard library's own
    # documented placement) each child would re-run the whole CLI from
    # scratch instead of just running its assigned worker function.
    multiprocessing.freeze_support()
    raise SystemExit(main())
