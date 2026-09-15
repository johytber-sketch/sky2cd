# sky2cd

`sky2cd` is a Blender preparation toolkit for artist-assisted Skyrim outfit work. It uses a game-agnostic `MeshIR` intermediate representation to make input inspection, safe geometry/axis conversion, and Blender handoff repeatable without claiming that an outfit is converted into a wearable game asset.

For a placeholder-only first run, see
[`docs/EXAMPLE_WORKFLOW.md`](docs/EXAMPLE_WORKFLOW.md). For a full practical
user guide covering install, first launch, the GUI, donor suggestions, and
troubleshooting, see [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md). Third-party
licensing and the current public-binary release blocker are recorded in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Supported workflow (read this first)

**`sky2cd` is not a fully automatic Skyrim-to-Crimson Desert wearable converter.**
The recommended workflow ends with a Blender preview/mockup that an artist evaluates
and develops manually. It does **not** produce a fitted, rigged, tested, or game-ready
outfit.

**What the Blender workflow provides:**
- NIF/archive intake plus safe geometry and axis conversion.
- A self-contained Blender handoff bundle: source preview OBJ(s), metadata, and an
  import script that labels assets for visual review.
- Explicit warnings and reports that distinguish preview/mockup geometry from a
  validated game asset.

**What the artist still owns:** body fitting, clipping fixes, material review, native
rig/weight transfer, rebuild/export, and in-game/animation testing. `sky2cd` does not
claim, infer, or certify any of those steps.

**Recommended workflow — Blender first, no donor required:**

```powershell
sky2cd blender-handoff --input outfit.zip --out .\handoff_out
# Open handoff_out\handoff\import_script.py in Blender. The imported source is a
# preview/mockup only: inspect, fit, clip, weight-paint, rig, and validate it manually.
```

**Optional donor reference:** when a donor helps the artist compare materials, scale,
or slot context, add `--piece`, `--packages-path`, and `--crimsonforge-home` to
`blender-handoff`. Donor lookup/export is optional and does not make a source mesh
fitted, weighted, or game-ready.

Avoid manually decoding catalog IDs by asking for a ranked recommendation:

```powershell
# Offline: slot and catalog-evidence ranking from the piece name.
sky2cd donors --suggest Dress_1.nif

# Keep the same payload next to working files for Blender/tool integration.
sky2cd donors --suggest Dress_1.nif --suggest-out .\donor_suggestion.json

# Enhanced: also verify the live game source, material/texture sidecars, resolved
# in-game name, and (for a readable single mesh) bounds-shape compatibility.
sky2cd donors --suggest .\Dress_1.nif \
    --packages-path "C:\...\steamapps\common\Crimson Desert" \
    --crimsonforge-home "C:\path\to\CrimsonForge"
```

The command prints one clear recommendation plus ranked alternates. It reuses the
existing donor catalog, slot inference, CrimsonForge verification/export, sidecar
lookup, and in-game-name resolver. Bounds comparison is included only when both source
and donor geometry can be read; otherwise the other evidence is reported without
inventing a geometry score. A recommendation is only a practical starting target for
artist review in Blender—it does not guarantee fit, clipping safety, rig/weight
correctness, animation safety, or a finished wearable/game-ready conversion.

Use terminal output for a quick decision. `--suggest-out` writes the same recommendation
as machine-readable JSON, including ranks, scores, reasons, verification/source signals,
and the artist-validation boundary. `blender-handoff` also writes
`donor_suggestion.json` beside each recognizable piece's `source.obj` and
`metadata.json`, so the recommendation stays with the Blender handoff files.

**Optional DMM packaging:** only after the artist has independently rebuilt and
validated a `.pac`, use `package-dmm [--strict]`. `--strict` checks sidecar presence,
optional CrimsonForge readability, and file provenance. It is a structural packaging
check—not validation of fit, clipping, weights, rigging, or in-game behavior.

**DMM live-donor-contamination caution:** never source a "donor" `.pac`/`.pac_xml` by
copying it out of an already-installed, third-party DMM mod's `files/` folder. That copy
may already be edited/rebuilt by that mod's author and is not the vanilla game asset —
using it silently propagates someone else's changes (and their license terms) into your
own package. Always export donors fresh from your own verified game install via
`sky2cd donors` / CrimsonForge, not from another mod's loose files.

`auto-replace`/`auto-replace-all` are retained as advanced experimental utilities for
a custom, already artist-validated body-fit config (`geometry_mode: "body_fit"`).
They are not the recommended workflow and never establish that the output is wearable
or game-ready. Without that custom config they refuse to produce a DMM package.

## Geometry safety correction (2026-09-13)

**The built-in `fem_kliff` and `cd_vanilla_female` presets are geometry/alignment
previews, NOT fitted bodies or game-ready conversions.** This supersedes earlier
claims below about reliable automatic fitting. The bundled Fem Kliff pair has only
19 vertices/18 triangles, all normals point in +Y, and the source has two degenerate
triangles. Both are rank-3 sparse proxies, not validated anatomical surfaces.

On the real Sherwood Huntress dress, the former unconditional collision pass was
the first destructive stage: it moved 24,033 of 47,063 vertices to nearest body
anchors, discarding tangential offsets, and created 45,549 degenerate triangles.
One anchor accumulated 8,488 vertices. IDW alone did not produce collapsed triangles,
but its proxy-driven deformation was not a meaningful Fem Kliff fit either.
Removing the source ground plane could never repair that damage.

The default now preserves source geometry with positive configured unit scaling and
exactly one `(x,y,z) -> (x,z,-y)` rotation at the Skyrim-to-OBJ boundary. It does not
fit a target pose, origin, or silhouette. GUI labels, reports, and warnings say
**preview only**; `auto-replace` and `auto-replace-all` reject preview presets before
opening CrimsonForge or game archives. The legacy inspection `.pac` emitted by
`convert` is still an invented debug format, not a rebuilt game PAC.

Additional corrections: automatic donor merge no longer rotates already-Y-up OBJ
geometry a second time; OBJ import/export flips UV V exactly once each way; each
submesh has an `o` boundary for CrimsonForge's importer; filtered NIF shapes retain
contiguous material indices; nine significant position digits avoid coalescing close
float32 vertices at metre scale. Normals are recomputed after nonlinear fitting.

**Source selection:** all NIF shapes are retained by default. A `Virtual` prefix
alone does not establish visibility or authoring-only status. Set
`"exclude_shapes": ["VirtualCBBE", "VirtualGround"]` in a custom preview config only
after inspecting that asset. Exclusions use exact names and emit warnings. In this
dress those shapes have empty texture maps and `NiShader`, and VirtualGround is a
four-vertex 160-by-160-unit plane. Their node flags do not mark them hidden.
The diagnostic previews keep both all-source and explicitly selected versions;
the textured source body and outfit triangles are not discarded.

**Recommended conversion method:**

1. Import and inspect the intact NIF in its authored coordinates. Establish one
   explicit unit/axis transform, then compare with the actual chosen target body
   in the same rest pose. Preserve topology, depth and material boundaries.
2. Obtain the real source body used by the outfit and the desired target body.
   Build a corresponding reshape of the source mesh against that target: identical
   vertex order and triangles, with correct anatomical correspondence. Two unrelated
   meshes with matching counts are not correspondence. Save this as a custom
   `geometry_mode: "body_fit"` preset only after checking it.
3. Fit garments using that pair and inspect each result. `build-preset` and conversion
   reject nonfinite, planar, missing/mismatched topology and degenerate references.
   These checks establish numerical prerequisites, NOT anatomical validity or mod
   provenance. IDW is an experimental approximation, not a general garment solver.
4. Collision correction is disabled unless `collision_max_distance` is explicitly
   supplied in body-reference units. The optional local pass requires a closed,
   consistently outward-oriented surface and usable normals, preserves tangential
   displacement, limits both sampling distance and movement, and rejects newly
   collapsed triangles. It is a local tangent-plane approximation, **not an
   inside/outside classifier**; deep intersections, concavities and sparse regions
   require a proper closest-surface/collision method and visual inspection.
5. Separately validate the target skeleton, bone mapping/weights, pose, material
   assignments and an offline PAC export/reimport comparison. Only then consider
   an in-game trial. Source Skyrim weights and donor proximity do not establish a
   correct CD rig. Mod installation is not part of geometry diagnosis.

Local comparisons are under `geometry_diagnostic_20260913`. The original stage
exports `00`-`04` and `baseline_metrics.json` preserve the failure evidence.
The primary corrected four-piece preview is `06_precision_geometry_preview`;
for Blender open `Dress_1\Dress_1.obj` (Y-up, configured scale) and its siblings.
The `_ALL_source_shapes_z_up.obj` files are raw Skyrim units, so do not overlay
them without the documented transform. `verified_metrics.json` records bounds,
depth, edge/area distributions, duplicate positions, source hashes and topology
checks. The corrected dress has zero degenerate triangles, maximum area
0.000337304 square metres rather than 0.135615522, and depth 0.382898 metres
rather than 0.170999. These are geometry-preservation results, not target-fit results.
Existing `dist` executables were not rebuilt during this diagnosis. Use the source
checkout via `.venv\Scripts\python.exe -m sky2cd.cli`; do not assume older executables
contain these safety gates.

### Local Fem Kliff reference candidates

Read-only inspection of the local mods found **Character Creator v7.9** by Khione
(Nexus 837), whose `Human Female` option contains appearance/customization descriptors
and textures, not a body PAC. Its Kliff (`cd_phm_macduff`) appearance references
`cd_phw_00_nude_00_0001_damian`, with `CharacterScale="0.94"`.
The default body option references skeleton variation
`1_pc/2_phw/nude/cd_phw_00_nude_00_0001.pabc`; six other body options also exist.
These file defaults are not evidence of the user's active customization or load order.

The local **Shapely Female Body** folder contains 1,937 PAC files and no DDS files,
including `0009\character\model\1_pc\2_phw\nude\cd_phw_00_nude_00_0001_damian.pac`.
It therefore supplies a geometry override for that default body name, not just a
texture replacement. No dependency/version manifest was present in that folder.
Offline parsing of this particular PAC yields 13,740 vertices and 25,158 triangles
across three submeshes (head, hands, body), with bone index/weight rows and no
degenerate triangles. It is a real reference *candidate*, not a validated target rig.
The seam-separated surface fails the closed-manifold collision requirement.

`geometry_diagnostic_20260913\07_target_reference_candidates` contains a raw-CD-axis
OBJ and `reference_findings.json` with source paths, hash, dimensions and checks.
The user confirmed **Character Creator + Shapely Female Body** as the intended
setup. The selected Body option and custom settings remain unconfirmed. In
Character Creator's **Body, Head and Face Details** tab, confirm whether Body uses
the first/default option (MeshParam 0, MeshSet 0, the Damian-named mesh above) rather
than one of the six alternate options. No saved-character config path was identified
in the inspected manifest/documentation, so no broad save/config search was performed.

Neither the appearance's 0.94 actor scale nor any live customization was applied.
`Shapely_body_parsed_geometry_and_weights.npz` preserves per-submesh geometry and
numeric weight/index arrays exactly as parsed, without renormalizing or assigning
invented bone names. `target_selection_and_weights.json` records hashes and the
skeleton references, which are not a parsed hierarchy or bind-pose skeleton.
**Rig blocker:** the parser returned empty influence rows and maximum weight sums
of only about 0.302/0.106/0.290 for head/hands/body. These are not verified complete
skin weights. They were preserved without normalization; the byte-identical original
PAC snapshot and `weight_decode_warning.json` preserve the evidence for validating
packing/implicit-weight semantics. Do not transfer or blindly normalize these rows.
Next establish the actual rest pose and runtime scale/customization behavior, then
construct source-to-target correspondence; these files do not supply a ready-made
Skyrim body correspondence.

### Offline alignment and skin-field follow-up

The user visually accepted the **06 dress geometry**, not its target-body fit or rig.
`geometry_diagnostic_20260913\08_offline_alignment_and_weights` now contains two
unchanged-geometry overlays: `01_DRESS_orange_TARGET_blue_RAW_REST_overlay.obj`
and `02_SOURCE_3BA_orange_TARGET_body_blue_RAW_REST_overlay.obj`.
Orange is source; blue/cyan is provisional Shapely. Only source unit/axis conversion
was applied; target coordinates remain raw. These are in the same coordinate
system, **not a verified shared skeletal rest pose**. In their common height range,
unsigned nearest-vertex mismatch has median 21.45 mm source-to-target / 20.78 mm
reverse, and 95th percentiles 58.61 / 62.20 mm. Sampling density, pose, silhouette
and differing body coverage contribute; these numbers are not penetration depths.

The external CrimsonForge reader's incomplete weights have a concrete explanation
supported by three local Shapely PACs (21,496 vertex records):

| Observed candidate field | Bytes within a 40-byte record |
|---|---|
| Six joint-table indices | Two little-endian uint32 words at 20 and 24, each containing three 10-bit indices |
| Six explicit weights | Six bytes at 28 through 33, interpreted experimentally as UNORM8 |
| Observed padding | High two bits of each index word, and bytes 34/35, all zero |

The current CF reader instead treats bytes 28-31 as indices and 32-35 as four
weights. All six-byte sums in these files are 253-257; no missing remainder or
normalization was added. Active body indices fit a 206-entry candidate identifier
table; the dress donor has a 71-entry table. All 71 identifiers match entries in
the body table, **all at different ordinals**. A raw PAC index therefore must not
be assumed to be the same index in `skeleton.bones`. CF currently fills its
descriptor `palette` from LOD-marker bytes, which is not a validated bone map.

This is still a **candidate layout, not a general PAC specification or a usable
rig**. The glove donor shares version/stride and skin-field structure but has an
unresolved metadata/table location. Version/stride alone cannot select a decoder.
The expected `0x3c000000` marker at byte 12 is absent in body/dress records and
present in gloves. Bone identifiers still require comparison with the actual PAB
hashes, hierarchy, bind matrices and selected PABC variation; socket XML is not a
substitute. The diagnostic-only `diagnostics.pac_skin_probe` and synthetic tests
are not wired into conversion or export. Six-slot evidence remains outside the
four-slot, normalizing `MeshIR` representation.

`offline_findings.json` records the exact external CF patch proposal and synthetic
fixture strategy; **no external code was modified**. Next confirm target Body
selection/customization, validate the correct offline skeleton/bind data, then
calibrate pose and anatomical landmarks before constructing a corresponding source
reshape. Do not fit by nearest vertices, equal counts, bounding boxes, or a global
`.94` assumption. No rig transfer, game writes, PAC rebuild or EXE build was done.

### Native six-influence record checkpoint (2026-09-15)

`sky2cd.pac.skin_records` now provides an **explicit-context, record-only codec**
and named PAB hash lookup. It is not imported by the conversion pipeline, native
PAC packaging or the debug PAC writer. It does not make the outfit fitted,
rigged, animated or game-ready. Existing `MeshIR` consumers are unchanged.

Public API:

```python
from sky2cd.pac.skin_records import (
    JointHashMapping, PabNamedRecord, SkinRecordContext, SkinRecordLayout,
    decode_skin_record, encode_skin_record, resolve_active_influences,
)

# These inputs come from independently inspected metadata, not guessed stride:
context = SkinRecordContext(
    layout=SkinRecordLayout.OBSERVED_PAR_01000903_SKIN40,
    joint_hashes=tuple(actual_joint_hashes),  # Python uint32 integers, original order
    evidence="Identification of inspected asset, record offsets and actual table",
)
record = decode_skin_record(original_40_bytes, context=context)
assert encode_skin_record(record) == original_40_bytes
# Verified named records in their original PAB order, not PAC table order:
mapping = JointHashMapping(context, tuple(verified_pab_named_records))
influences = resolve_active_influences(record, mapping)
```

`NativeSkinRecord` is frozen, with immutable bytes and tuples. It retains all
six indices and raw weight bytes, including inactive indices outside the table.
Only **nonzero-weight indices** must be in bounds. `weights_unorm8` divides each
byte by 255 without normalizing, truncating, sorting or inventing a remainder.
There is no influence-editing, quantization, `MeshIR` adapter or complete PAC
writer API. The encoder repacks the two index words and six weights into the
original 40-byte record; all other bytes are preserved.

The caller must explicitly select the observed layout and supply a unique actual
joint hash table and an evidence description. This is an **asserted context,
not automatic detection or independent authentication**. Version/stride, padding
and plausible weight sums alone are insufficient. The codec reuses the existing
probe's fail-closed checks: high two bits of each word and bytes 34/35 must be zero;
six weight bytes must sum to 252..258 (the existing six-UNORM8 rounding envelope).
Real tested records sum to 253..257. Nonzero padding is rejected, not zeroed.
Bytes 0..19 and 36..39 remain opaque, including variant values at byte 12.

`PabNamedRecord(record_index, joint_hash, name)` stores identity only.
`JointHashMapping` rejects duplicate hashes/names, missing matches and incorrect
PAB record order. Each result separately exposes PAC joint-table index, uint32
hash, PAB record index and stored name. It does not establish that a PAB ordinal
is an animation/runtime bone index. For the preserved Pro original:

| PAC table index | Hash | PAB record index | Stored name |
|---|---|---|---|
| 0 | `0xa23a288e` | 97 | `Bip01 Head` |
| 137 | `0xbc1d1337` | 17 | `Bip01 R Thigh` |
| 153 | `0xd17d9109` | 18 | `Bip01 L Thigh` |

All 206 Pro hashes match uniquely among 448 named PAB records; **none** shares
its PAC table ordinal with its PAB record ordinal. These are identifier matches,
not anatomical side assignments. Actual Pro body vertex 82 has six nonzero raw
weights `(94,65,44,30,17,5)` and table indices `(138,142,143,161,139,148)`;
all six are retained and named in the local report.

Validation from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skin_records.py tests\test_pac_skin_probe.py tests\test_meshir.py tests\test_pac_writer.py
.\.venv\Scripts\python.exe geometry_diagnostic_20260913\24_native_skin_records\validate_local.py --output geometry_diagnostic_20260913\24_native_skin_records\record_roundtrip_repeat.json
```

The second command needs the user's **already-preserved private snapshots**,
not live game access, Blender, CrimsonForge, extraction or redistribution.
Choose a new output filename on each run; existing reports are never overwritten.
Synthetic tests ship without proprietary assets. Do not share local snapshots
without the respective third-party permissions.

Measured local checkpoint: **32,376 complete records / 1,295,040 bytes repacked
exactly**, including 6,639 records with six active slots. This covers 13,740 Pro
original records plus 18,636 of the earlier 21,496 sampled records. Pro and
Shapely body rows were checked against preserved PAC bytes at every saved
record offset; the 4,896 dress rows were checked against saved record arrays
only, without reopening the external donor. The 2,860 glove rows remain
**excluded** because their actual joint table is unresolved. Empty-table context
construction fails rather than pretending they passed.

The validator also checks all 448 PAB hashes/names against the SHA256-identified
local PAB bytes, original record offsets and saved structural arrays; the 5,854
trailer bytes and matrix/controller semantics remain outside this API.
`24_native_skin_records\record_roundtrip.json` contains per-part byte hashes,
sample six-slot mappings, input hashes and limitations. This validates preserved
snapshot identity, not vanilla/live load order.

**Next prerequisite for NIF-to-native-CD rest-pose remapping:** establish the
effective CD mesh bind/rest frame including the selected PABC variation, then
pair actual spatial joints with per-shape stored NIF skin transforms. The
retained phase10 calibration supports PAB global/inverse/local matrices, but
PABC has parent-chain exceptions (including clavicles/neck) and three ear-global
exceptions. The source also has stored twist-bind inconsistencies (HaleSkirt
left-labelled upperarm twist and several embedded3BA twists). Neither can be
silently replaced by generic node transforms, a literal L/R-name match, a
normalized four-slot array or a new runtime skeleton. Native bind interpretation,
source-to-target pose correspondence, weight transfer, fitting and animation
remain separate uncompleted steps. Body Slider changes body geometry; it does
not resolve these bind/rig requirements.

### Bind/rest-frame follow-up (2026-09-15)

`sky2cd.weights.transform_checks` adds pure `local_to_global`,
`inverse_pair_errors`, `skin_bind_closure`, `affine_difference` and `change_basis`
checks. Each requires an explicit row/column convention; matrices keep their
non-unit scale. Residuals are reported, not converted into rig approval.
There is no production integration, pose fitting or weight modification.

The preserved-data investigation explains the former 18 PABC chain exceptions
**algebraically**: extra stored scale factors account for 13, and five unique
alternative-parent matrix matches account for the remainder. The proposed
`A @ local @ B` row-vector composition, including translation scaling, closes
436/436 non-root chains (maximum error `1.4253e-5`). The inferred parent graph
is acyclic but is **not a decoded or runtime-verified hierarchy**.

The three right-labelled ear globals differ by an approximately local 180-degree
frame rotation, with almost unchanged origins. Mixing those PABC globals with
the stored PAB inverses fails; it must not be hidden by recomputing inverses.
Source native readback also confirms that tiny shape transforms do not explain
the one HaleSkirt/six embedded3BA twist discrepancies: independent shapes agree
on stored-bind frames, while current node linear frames differ. Keep per-shape
stored binds; do not substitute current node globals or match literal L/R labels.

Details, exact offsets, affected Pro influence counts, rejected hypotheses and
remaining runtime evidence requirements are in
`geometry_diagnostic_20260913\25_bind_rest_frames\RESULT.txt` and
`bind_frame_verified.json`. The supported algebraic subsets are **not transferable
outfit rigs**. The next gate is evidence of effective PAB/PABC runtime frame
selection and compensation, followed by spatial source/CD joint correspondence.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_transform_checks.py tests\test_skin_records.py tests\test_pac_skin_probe.py tests\test_meshir.py tests\test_sidecar.py tests\test_pac_writer.py
.\.venv\Scripts\python.exe geometry_diagnostic_20260913\25_bind_rest_frames\investigate.py --output geometry_diagnostic_20260913\25_bind_rest_frames\bind_frame_repeat.json
```

The second command needs the existing private snapshots and original Sherwood
NIF at its recorded path. It only reads them and writes a **new** report inside
phase25; it never opens game archives, edits the NIF or runs external parser code.

### Garment-connection isolation

`geometry_diagnostic_20260913\09_garment_connections` isolates the reported missing
connections without modifying accepted previews or production body handling.
`Dress_1_CLOTHING_ONLY_OPAQUE.obj` contains all three native garment shapes
(26,521 vertices / 50,760 triangles), with named groups and opaque diagnostic
materials. `SOURCE_BODY_AND_CLOTHING_CONTROL_NOT_TARGET.obj` adds only the original
embedded 3BA body. Import either control **alone in a fresh Blender scene**, not
over the other previews.

Native-shape comparison confirms that `HaleSkirt`'s front connections survived
06/01. Front-view controls reproduce their occlusion by the provisional Shapely
body, while they remain visible with source 3BA. Both bodies' anterior sides face
negative Z; there is no relative yaw reversal in the saved coordinates.
All three garment diffuse textures have fully opaque alpha, and the source
garments have no NiAlphaProperty. Source physics XML separately identifies the
excluded body/ground collision helpers.

The isolated source has an open upper back and a native rear skirt below the
belt. The reported full upper-back panel is **not reproduced** by these controls;
existing-scene imports, transforms and display settings remain to be checked.
Do not delete faces or rotate the garment to hide that discrepancy.
`garment_findings.json`, per-shape preservation records, and front/back/side
diagnostic images document the evidence and limitations.

## What works now

- `blender-handoff` — the headline command. Converts a Skyrim outfit/archive, exports each requested real donor item (materials/textures + `.pac_xml`/texture sidecars via CrimsonForge, when a game install is given), and writes a self-contained per-piece handoff directory (source `.obj`, donor `.obj`, `metadata.json` with explicit "NOT FITTED" status + provenance, and a generated Blender `import_script.py`). Never packages a DMM mod and never requires a validated body-fit config.
- `package-dmm --strict` — optional, opt-in pre-flight validation for an artist-supplied rebuilt `.pac`: requires its matching `.pac_xml` sidecar to be supplied via `--sidecar`, optionally verifies the `.pac` parses via CrimsonForge (`--crimsonforge-home`), and writes a `provenance.json` (sha256 of every packaged file). Default (non-strict) `package-dmm` behavior is unchanged.
- `MeshIR` stores positions, normals, UVs, triangle indices, bone names, bone indices, bone weights, and materials, with a simple `.meshir.json` + `.npz` round trip.
- Skin weights can be exported to and restored from a `.cfmeta.json` sidecar. Reapplication first uses stable vertex indices/positions and falls back to nearest-position matching when topology changes.
- IDW body-conforming deformation is fully implemented with NumPy and SciPy `cKDTree`.
- An opt-in, bounded local clearance approximation is available for validated surfaces; it is not an inside/outside solver (see geometry safety correction above).
- Skyrim biped slots are resolved through an editable JSON resource to Crimson Desert equipment-slot hash targets, merge fallbacks, or unsupported mappings, with a per-run mapping report.
- The CLI supports single meshes as well as `.7z` and `.zip` mod archives:

  ```powershell
  sky2cd convert outfit.7z --body-config body-config.json --deformer idw --out out
  sky2cd report out\conversion-report.json
  ```

- A tkinter desktop GUI (`sky2cd.gui`) wraps the same pipeline: file/folder pickers (supporting `.nif`, `.meshir.json`, `.7z`, `.zip`), a deformer dropdown, a background-threaded Convert button that keeps the window responsive, a scrolling status/error log, and Show report / Open output folder buttons. It calls the real `sky2cd.pipeline.convert` — no simulated conversion — and surfaces every exception verbatim in the log and a message box.
- **Mod archive extraction:** `.7z` and `.zip` mod packages can be dropped in directly. `sky2cd` extracts them, discovers all outfit meshes inside (preferring max-weight `_1.nif` variants when both `_0` and `_1` are present), and batch-converts all pieces to PAC files with a unified conversion report.

The project intentionally uses `argparse` from the Python standard library instead of Click to keep runtime dependencies minimal.

## Reality check: is the `.pac` output actually usable in-game? (No — and here's why)

As of 2026-09, **converted meshes cannot be loaded into Crimson Desert**, and this is not
a bug in this pipeline's logic — it's because the real mesh geometry binary format is not
publicly reverse-engineered yet, by anyone, including the most advanced open community
tool.

Cross-referenced against a real Crimson Desert modding guide (DMM / "Definitive Mod
Manager" workflow) and [`dmm-parser`](https://github.com/exodiaprivate-eng/dmm-parser)
(509 passing tests, 122+ tables decoded):

- `.pac` is a **PAR-family archive container**, not a flat vertex buffer — and even that
  container is only partially cracked (24/30 sample files extractable; 6 need IDA-level
  reverse engineering of a compression variant).
- `.pami` / `.pamlod` are XML/metadata wrappers that *point at* mesh data — they are not
  the geometry itself.
- The actual mesh **vertex/index geometry format** (`.meshinfo` and related) is in
  `dmm-parser`'s own "🚫 blocked" / "⚠️ unparsed long tail" bucket — nobody in the public
  modding community has cracked it yet.
- This project's `sky2cd.pac.writer.write_pac` (40-byte vertex stride: quantized
  position, float16 UV, packed normal, bone indices/weights) was an **invented,
  best-guess format** with no relation to the game's real binary layout. It was always
  going to produce a file the game can't read — that was true before this note existed,
  it just wasn't stated this plainly.

**What is actually solvable today, per the same guide:**

- **Tier 1 — reskins with no mesh work.** Clone an existing item record (`clone_record`
  on `iteminfo`), give it your own name/description/stats/passives, and put it on a
  vendor or drop table. This reuses a vanilla mesh — no Skyrim-mesh conversion involved
  — and is confirmed working in-game. This is a completely different tool from
  `sky2cd`'s mesh pipeline; it would use `dmm-parser`'s `pabgb`/`paloc` table APIs and
  Field-JSON v3.1 intents instead.
- **Tier 2 — your own mesh, on a free slot.** Solved for weapon families that don't
  sheathe (shields, pikes, bows, fists, etc.). Still requires writing a real mesh in the
  game's actual binary format at that slot — which circles back to the blocker above.
  Armour is measured but nobody has shipped a working custom-mesh armour item yet.
- **Tier 3 — sheathing weapons (swords, etc.):** only partially solved even by the guide
  author; scabbards must currently be borrowed from a vanilla weapon.

**Historical assessment (superseded by the geometry safety correction above):**
`sky2cd`'s MeshIR pipeline provides reusable groundwork, but the final
"write it as a real Crimson Desert asset" step is currently a research problem, not an
engineering one — it requires reverse-engineering an undocumented binary mesh format,
which is a different (and much larger, uncertain) kind of project than converting the
mesh math itself.

### Does a "transmog" mod solve this? No — checked, and here's why

It's a reasonable idea: if a transmog/appearance-swap mod can change what mesh displays
on a character without touching the item database, maybe it sidesteps the mesh-format
problem entirely. I checked the actual implementation of the community's mesh-swap tool
([`character_mesh_swap.py`](https://github.com/NattKh/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS/blob/main/CrimsonGameMods/character_mesh_swap.py),
part of the CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS toolkit) to see how it actually
works under the hood.

It works by editing one field: it copies the **appearance-hash pointer**
(`_appearanceName`, `lookup_22` in `character_info`) from a *source* character/item onto
a *target* one. That's it — it's a "point B at whatever A already points at" operation.

That means transmog/mesh-swap can only make an item display a mesh that **already
exists validly in the game's own binary format** (i.e. some other vanilla or already-
working custom asset). It cannot inject a brand-new mesh — Skyrim-derived or otherwise —
that has never been written in the game's real geometry format. **The blocker above
(nobody has cracked the mesh binary format) still applies**; transmog just changes
*which* existing asset a slot points to, not *whether* a wholly new asset can exist at
all.

**What this means for a fem-kliff-style workflow specifically:** transmog could let you
reassign an *existing* CD outfit (already in the game) onto a different equipment slot
or NPC — useful for costume mixing among stock assets — but it cannot make a *converted
Skyrim mesh* appear, because that mesh was never written as valid CD geometry in the
first place.

## Historical research: external tooling and optional packaging

This section records research into external tooling and advanced packaging paths. It
does not change `sky2cd`'s Blender-focused scope: neither donor selection, automated
steps, nor a packaged file establishes a fitted, rigged, wearable, or game-ready
result. Treat these paths as optional support for an artist's independently validated
work, not the primary workflow.

The sections above were correct as of when they were written, but they missed the
tooling the actual Crimson Desert modding community already uses. Two things changed
this:

**1. `CrimsonForge`** ([github.com/hzeemr/crimsonforge](https://github.com/hzeemr/crimsonforge),
MIT, v1.11.0) has genuinely reverse-engineered the real mesh geometry format: quantized
`uint16` positions dequantized against a per-file bounding box, `float16` UVs, submesh
tables at documented byte offsets, real bone-weight slots — the real version of what
`sky2cd.pac.writer` only guessed at. It can export any in-game item to OBJ/FBX, reimport
an edited mesh (including topology changes), and patch it back into a valid, loadable
`.pac`/`.pam` (recompression, re-encryption, checksum rewrite included).

**2. Community body-refit tools already exist and are purpose-built for exactly this:**
[**Body Slider Pro**](https://www.nexusmods.com/crimsondesert/mods/2727) and
[**Body Slider Outfitter**](https://www.nexusmods.com/crimsondesert/mods/2993). These
are the tools the CD outfit-modding community actually uses to conform an outfit's mesh
to a custom body shape and batch-process penetration fixing — this overlaps
significantly with what `sky2cd`'s own IDW deformer + `fix_penetration` step were built
to approximate from scratch. They take a target body `.pac` as a "Custom Slider" input
and a folder of outfit models, and their batch workflow has a **built-in "Penetration
Fix" checkbox** — i.e. the community has already solved body-conforming with access to
the game's real skeleton/weight data, which `sky2cd` never had.

### The real, confirmed workflow (from a shipped mod's own documentation)

This is transcribed from the author's own notes on
["Dawnbreaker Set (Fixed Physics)"](https://www.nexusmods.com/crimsondesert/mods/3446),
a real, working 4-slot armor replacer (helm/cuirass/gloves/boots) built from unused game
assets — confirming every step below is achievable in practice, not theory:

**A. Getting the outfit onto a body (refit):**
1. Add your target custom body `.pac` into **Body Slider Pro** as a **Custom Slider**.
2. Export it as a **Character Pack**.
3. Import that Character Pack into **Body Slider Outfitter**.
4. Run **batch processing** — check the **"Penetration Fix"** option.
5. Outfitter generates outfit model files for your slider in an `exported_outfit`
   folder. **Replace those generated files with your actual outfit's mesh files**
   (this is where `sky2cd`'s converted/deformed `.obj` output slots in).
6. Export the Character Pack again, then load it in Body Slider Pro to fine-tune the fit.

This confirms `.obj` is exactly the right hand-off format — the mod author explicitly
ships `.obj` files in their own "Miscellaneous Files," matching what `sky2cd` already
produces. `sky2cd`'s job is to get a Skyrim mesh into that `exported_outfit`-ready OBJ
shape (right scale, right axes, already roughly conformed) before it goes through Body
Slider Outfitter's real, engine-accurate refit pass.

**B. Getting cloth/physics working (the part `sky2cd` explicitly cannot do):**

The author's own explanation, condensed: physics/cloth behavior lives on the mesh's
*rig/submesh structure*, not something a converter can synthesize. Their technique was a
**donor-merge**:
1. Find an existing CD armor piece already known to have working physics (they cite
   specific part IDs, e.g. `cd_phw_00_ub_inner_0003` for upperbody, `cd_phw_00_lb_00_0145`
   for lowerbody) — this is your **physics donor**.
2. In your mesh editor, merge your new/converted geometry onto the donor, and shrink the
   donor's own geometry down inside the body so it's hidden (not deleted — its physics
   rig binding needs to remain intact for cloth-sim to keep working).
3. **Match submesh counts.** If the target outfit has more submeshes than the donor
   (their example: donor had 1 usable submesh, their real Dawnbreaker armor had 3), the
   submeshes must be merged/consolidated to match, or per-submesh textures will map
   incorrectly. Retexture as needed to preserve the original look.
4. Expect this to be finicky and outfit-specific — the author states plainly it was "a
   long and complicated process" even for someone who does this regularly. There is no
   way to script this reliably without a general solver for the game's cloth-rig format,
   which is a separate, unsolved research problem — same caveat that applies to the
   `.pac` binary format in general.

**Practical, unrelated tip also confirmed by the same mod:** use
[**Gear Hider**](https://www.nexusmods.com/crimsondesert/mods/554) with a
`CrimsonDesertEquipHide.ini` preset to hide underwear/shoulder-guard accessories that
would otherwise clip through a replaced outfit — nothing to do with `sky2cd`, but useful
for a clean-looking result.

### VERIFIED (against the real game + real CrimsonForge source): `sky2cd merge` + CrimsonForge's own rebuild DOES auto-infer weights for new geometry

This was tested directly against the user's actual installed Crimson Desert (Steam,
v2.02.00) and CrimsonForge v1.26.0's real Python source (not the changelog prose, and
not our earlier guess) — see below for exactly how.

An earlier revision of this README claimed the opposite, based on a changelog line
about a **different, stricter** code path ("strict skin write-back via v2 cfmeta
sidecar", used for the FBX-based full-reskin workflow). That claim was **too broad**.
The simpler **OBJ → PAC** path that `sky2cd merge`'s output actually targets behaves
differently, and was confirmed to work as follows:

- `core.mesh_importer.build_pac()` (CrimsonForge's real PAC rebuilder) requires the
  edited `.obj` to be re-imported **over the donor's own CrimsonForge-exported `.obj`**
  (same file, keeping its `# source_path:` / `# source_format:` header comments) plus
  the donor's original `.pac` bytes.
- When the vertex/face count changed (exactly the `sky2cd merge` case — new outfit
  vertices appended), it calls an internal **`_build_pac_full_rebuild`** path. For every
  new vertex with no recorded source index, it calls **`_choose_pac_donor_indices`** — a
  real, working, positional-nearest-neighbor search (exact-match dict + spatial hash for
  larger meshes) that clones the **entire raw vertex record** (bone indices, bone
  weights, packed normal, everything) from whichever *original* donor vertex sits
  closest in 3D space.
- **We ran this for real**: exported the two real donor PACs named in the Dawnbreaker
  mod's own writeup (`cd_phw_00_ub_inner_0003.pac`, `cd_phw_00_lb_00_0145.pac`) straight
  from the installed game via `VfsManager`, ran a `sky2cd`-converted synthetic outfit
  through `sky2cd merge` logic, appended it onto the donor's real exported `.obj`, and
  called `build_pac()` with **no `.cfmeta.json` sidecar for the merged file at all**.
  - It **succeeded without error**, producing a valid rebuilt `.pac`.
  - Re-parsing that rebuilt `.pac`: new vertices placed near an already-weighted donor
    vertex **correctly inherited its real bone index + weight** (e.g. `bone_idx=(190,)
    bone_w=(0.0235,)`), automatically, with no manual step.
  - New vertices placed near a donor region that itself had **no** weight (roughly half
    of this particular donor's ~639 vertices are unweighted — likely rigid/static
    portions of that item) correctly inherited **empty** weights too — i.e. it behaves
    exactly like "clone the nearest donor vertex's own attributes," not magic.

**What this means in practice:** `sky2cd merge`'s output is not just a Blender-import
starting point — feeding it back through CrimsonForge's own OBJ-import + `build_pac()`
pipeline against the donor's real exported `.obj`/`.pac` pair can produce genuinely
weighted geometry with **zero Blender weight-painting**, *provided* your merged geometry
sits close enough to donor regions that actually carry weight data. Where the donor
itself is sparsely weighted (physics/cloth items can be), some new vertices will come
out unweighted — the same regions a manual weight-paint pass would need to touch up
regardless, but now as a smaller, optional cleanup step rather than a mandatory one.

**Still true and unavoidable:**
- The donor and your working `.obj` must be the **same file lineage** (edit the donor's
  own CrimsonForge-exported `.obj` in place — don't build an unrelated merged file from
  scratch) so `build_pac()` can locate the right original `.pac` and vertex records.
- `build_pac()` **requires the submesh count to match the original** (`sky2cd merge`'s
  `nearest` submesh strategy exists specifically to satisfy this).
- This does not solve **rig/skeleton bone selection** for genuinely new bones, or
  cloth-physics **behavior** tuning — only *weight/bone-index cloning* from the nearest
  existing donor vertex.

**CrimsonForge also ships a real Blender addon** (as of v1.26.0's second download,
`crimsonforge_blender.zip`, Blender 4.2+) with **Browse Game** (imports a `.pac` with its
real `.pab` skeleton + textures attached), **Export to Game**, **Import Complete
Character**, and **Import Animation** operators. This remains the better choice when you
want full manual control over weight-painting or need a genuinely new bone/skeleton
setup — `sky2cd merge` + `build_pac()` is the better choice when you just want the
verified-working, no-Blender path for merging onto an existing donor's own weight field.

### Recommended end-to-end workflow using `sky2cd`

1. **Convert with `sky2cd` as usual** (`sky2cd convert outfit.nif --body-config fem-kliff --out out`).
   This produces `out/outfit.obj` (+ `.mtl`) — Skyrim's mesh, deformed toward the target
   body and axis-converted to Crimson Desert's Y-up (Maya) convention.
2. **Body-conform it properly** by running that `.obj` through the **Body Slider Pro +
   Body Slider Outfitter** batch-processing workflow above (with "Penetration Fix"
   checked) — this gets you engine-accurate conforming that `sky2cd`'s own IDW deformer
   only approximates.
3. **Pick a donor CD item slot to replace** (a compatible existing armor/weapon slot).
   Use **CrimsonForge** to export that donor's real mesh/rig (with `.cfmeta.json`
   sidecar for bone weights) as your merge target.
4. **If you want working cloth physics**, apply the donor-merge technique above: merge
   your conformed outfit onto a known-physics-working donor from a similar body region,
   shrink the donor's own mesh to hidden, and reconcile submesh counts. If physics
   doesn't matter for your use case, you can skip this and use a simpler direct swap.
5. **Reimport via CrimsonForge** (OBJ or FBX) and use its **Import + Patch to Game**
   action to produce a valid, loadable replacer `.pac`.

**On DMM ("Definitive Mod Manager") and reversibility -- corrected, verified against a
real, installed DMM copy with real, currently-mounted mods:** the `dmmgen`/`dmmsa`/
`dmmv3_*`/`dmmvoice` folders inside the game install are Pearl Abyss's own live-content
package groups and are unrelated to the third-party "DMM" mod manager most of the
community actually uses.

That third-party DMM (and other loose-file-aware managers like CDUMM/Crimson Browser)
uses a much simpler, much safer format that requires **no in-place game archive
patching at all**: a mod folder containing a `manifest.json` plus a `files/` directory
whose contents mirror the game's own real VFS-relative paths, e.g.
`files/character/cd_phw_00_lb_00_0182.pac`. DMM mounts these as a virtual overlay at
runtime. CrimsonForge itself already ships this exact export format (`kind:
"mesh_loose_mod"`, `manifest.json` + `modinfo.json`), confirmed from a real
CrimsonForge-generated mod already mounted in a live DMM install -- so this is the
verified, community-standard target, not a guess.

`sky2cd` now reproduces this same schema directly via `sky2cd.dmm_package` /
`sky2cd package-dmm`, so a converted+merged `.pac` can go straight from `sky2cd merge`
to a droppable DMM mod folder:

```
sky2cd package-dmm --pac merged_donor.pac --entry-path "character/cd_phw_00_lb_00_0182.pac" \
    --package-group 0009 --title "My Armor Replacer" --game-build "v2.02.00" --out ./dmm_out
```

**Real, confirmed requirement — sidecar files, not just the `.pac`:** comparing our
early packages against a real, currently-installed and working reference DMM mod
(inspecting its actual `files/` folder directly) showed it ships, per replaced item,
not just the `.pac` but also that item's real `.pac_xml` (material/skin-binding XML)
and its texture `_n`/`_disp`/`_ma`/`_mg`.dds files — a package with only the `.pac` is
missing them and will not look right in-game. `sky2cd.crimsonforge_bridge` now reads
these real sidecar files straight from the game's own VFS (matched by basename, not a
hardcoded folder layout — the real on-disk paths for these files aren't consistent
across items) and `auto-replace`/`package-dmm` bundle them automatically alongside the
`.pac`. Note this carries over the **donor's own original textures**, not the source
Skyrim mod's actual look — Crimson Desert has no equivalent asset for a Skyrim-only
mod's textures, so porting those over would need a separate UV/channel-repacking
feature, not attempted here.

Reverting is simply disabling/deleting the mod folder in DMM -- the base game's
`.paz`/`.pamt`/`.papgt` archives are never touched, so no backup/restore step is even
needed for this route. (The older in-place `repack_relative_files()` path, with its own
automatic backup/restore via `BackupManager`, is still available in `pipeline.py` for
the rare case where a target isn't loose-file-overridable, but it is no longer the
recommended default.)

**Important limits, stated plainly:**
- It is a **replacer** — the donor item's original look is gone while installed, and it
  can't coexist with another mod replacing the same slot. That matches "1 mod at a time
  per install" exactly.
- Re-skinning/rig work is manual and per-outfit — `sky2cd` cannot infer bone bindings or
  auto-solve cloth-rig compatibility; this is genuine 3D-modeling work.
- CrimsonForge, Body Slider Pro, and Body Slider Outfitter are all separate, independent
  community tools `sky2cd` does not vendor or depend on — install and run them
  separately (except CrimsonForge's donor-export/rebuild step, which can now be fully
  automated -- see the next section).

## Optional donor catalog and experimental automation (`sky2cd donors` / `sky2cd auto-replace`)

These optional advanced utilities can assist an artist who has already established and
validated a custom body-fit workflow. They are not the recommended Blender workflow
and do not automatically convert a Skyrim outfit into a wearable or game-ready asset.

**1. Donor Catalog (`sky2cd.donor_catalog`)** — a small, *metadata-only* list of known
Crimson Desert items usable as replacer targets (display name, slot, real VFS path,
package group, physics/dye notes). **We never bundle the actual donor mesh/texture
bytes** — those are Pearl Abyss's own copyrighted game assets and always stay wherever
the user's own Steam install already has them. `sky2cd donors` lists the catalog;
`sky2cd donors --verify --packages-path <dir> --crimsonforge-home <dir>` checks every
entry against a real, live install (since a game patch can move/rename items between
builds) via CrimsonForge's own `VfsManager`. Add `--ingame-names` (with the same two
paths) to also resolve and print each entry's real in-game display name next to its
cryptic path (via `sky2cd.crimsonforge_bridge.build_item_name_resolver`), so you can
match a catalog id to what the item is actually called in-game before picking it for
`blender-handoff`/`auto-replace`.

**2. CrimsonForge bridge (`sky2cd.crimsonforge_bridge`)** — CrimsonForge is MIT licensed
(verified from its real `LICENSE` file), so we could vendor it, but deliberately don't:
its mesh-editing logic is substantial, independently-maintained software, and bundling a
copy would mean carrying a permanently stale fork. Instead this module locates a
**separate, already-installed** CrimsonForge copy (explicit path, `CRIMSONFORGE_HOME` env
var, or common install locations — the same "point us at your existing install" pattern
FNIS/BodySlide already use for Skyrim) and calls its real, importable `core` functions
directly: `parse_mesh` (read a real donor `.pac`'s bytes), `export_obj` (donor -> `.obj`),
`import_obj`/`build_pac` (merged `.obj` -> rebuilt, loadable `.pac`). No CrimsonForge GUI
interaction is required for any of this.

**3. `sky2cd auto-replace`** ties it all together into one command: Skyrim outfit ->
`convert` -> read the real donor `.pac` straight out of the live game -> `merge_onto_donor`
-> CrimsonForge rebuild -> `package-dmm`. One droppable mod folder out, nothing manual in
between:

```
sky2cd auto-replace --input outfit.nif --donor-id demenissian_elite_leather_lb \
    --packages-path "C:\...\steamapps\common\Crimson Desert" \
    --crimsonforge-home "C:\path\to\CrimsonForge" \
    --title "My Armor Replacer" --game-build "v2.02.00" --out ./out
```

**Real, confirmed gap (found via live in-game testing), now fixed — multi-piece
outfits:** a Skyrim outfit archive can (and often does) contain several separate armor
pieces as distinct `.nif` files, not one. The real Sherwood Huntress archive has
**4**: `Boots_1.nif` (68,874 verts — actually the largest piece, likely the real
dress/body mesh despite the misleading name), `Dress_1.nif` (47,472 verts),
`Gloves_1.nif` (19,766 verts), and `Hood_1.nif` (61,425 verts). `sky2cd.pipeline.convert()`
already converted every piece found in the archive, but `auto-replace` used to always
take only the first one and silently discard the rest — the real, confirmed cause of an
early test where only the lowerbody slot changed and everything else (correctly)
looked unchanged. `auto-replace` now:

- accepts `--mesh-selector <text>` — a case-insensitive substring match against each
  piece's path (e.g. `--mesh-selector gloves`) — to pick which piece gets merged onto
  `--donor-id` for that run;
- defaults to the first piece found if `--mesh-selector` is omitted (unchanged
  behavior for single-piece outfits);
- always prints (and raises a Python `warnings.warn`) a clear list of which other
  piece(s) were converted but *not* packaged this run, so nothing is silently dropped.

**Update — now batchable in one command:** `sky2cd auto-replace-all` converts the
archive once, then merges/rebuilds *every* requested piece and combines all of them
into a single DMM package folder, so a full 4-piece outfit (boots/chest/gloves/hood)
becomes one command instead of four separate `auto-replace` runs:

```
sky2cd auto-replace-all --input outfit.zip \
    --piece "boots=demenissian_elite_leather_lb" \
    --piece "dress=demenissian_elite_leather_ub" \
    --piece "gloves=proxima_ref_hands" \
    --piece "hood=proxima_ref_head" \
    --packages-path "C:\...\steamapps\common\Crimson Desert" \
    --crimsonforge-home "C:\path\to\CrimsonForge" \
    --title "My Armor Replacer" --game-build "v2.02.00" --out ./out
```

Add `--max-workers -1` (or an explicit count like `--max-workers 4`) to rebuild multiple
pieces' `.pac` files concurrently in separate processes — see "Pipeline performance"
below for why this helps (CrimsonForge's own rebuild step, not sky2cd's Python code, is
the real per-piece bottleneck) and what it requires in a frozen `.exe` build.

Each `--piece "mesh_selector=donor_id"` picks one converted piece and the donor it gets
merged onto; any piece in the archive not covered by a `--piece` flag is reported (both
printed and via `warnings.warn`) as unmatched, same as plain `auto-replace`'s single-
piece warning. **Verified live**: a real run against the full Sherwood Huntress archive
(4 pieces) with all 4 donors above converted the archive once and merged/rebuilt every
piece — `Boots_1` onto the lowerbody donor (58,656 verts merged), `Dress_1` onto the
upperbody donor (54,432 verts, 3 submeshes), `Gloves_1` onto the hand donor (44,600
verts, 2 submeshes), and `Hood_1` onto the head donor (62,998 verts merged) — landing
all 4 real, CrimsonForge-rebuilt `.pac` files plus their sidecars in one combined DMM
package folder.

**Update — `--piece` is now optional, auto-donor-selection:** typing a `--piece
"selector=donor_id"` for every single piece defeats the point of an "automated" tool,
so `sky2cd auto-replace-all` no longer requires it. Omit `--piece` entirely and it
auto-selects a donor for every piece instead:

```
sky2cd auto-replace-all --input outfit.zip \
    --packages-path "C:\...\steamapps\common\Crimson Desert" \
    --crimsonforge-home "C:\path\to\CrimsonForge" \
    --title "My Armor Replacer" --game-build "v2.02.00" --out ./out
```

`sky2cd.donor_auto_select` guesses each piece's Crimson Desert slot from its filename
(e.g. `"Gloves_1.nif"` → `hands`, `"Hood_1.nif"` → `head`, `"Dress_1.nif"` →
`upperbody`) using the same substring-matching style `--mesh-selector` already relies
on, then looks it up against the built-in `sky2cd.donor_catalog`:

- A piece **auto-resolves** only when exactly one catalog donor matches its guessed
  slot — this is the common case for the catalog's current single-donor-per-slot
  entries, and needs zero prompts.
- A piece is **ambiguous** if more than one catalog donor matches its guessed slot: it
  is *not* auto-converted (no guess is made among multiple candidates); the run prints
  every candidate donor id for that piece so you can cover it with an explicit
  `--piece "selector=donor_id"` instead.
- A piece is **unmatched** if no keyword matched its filename at all, or no catalog
  donor exists for the guessed slot — reported the same way `--piece`-mode already
  reports uncovered pieces.

**Real limitation, by design:** Skyrim's actual body-slot assignment lives in the
plugin's (`.esp`/`.esl`) `ARMA` record's biped-model bitfield, not the `.nif` mesh file
itself, and `sky2cd` never reads plugins — only loose mesh archives — so this is always
a best-effort filename guess, never a guaranteed-correct detection. You can still mix
`--piece` flags for specific pieces with omitting others once explicit `--piece` support
for partial overrides lands; today, using any `--piece` flag at all switches the whole
run back to fully-manual mode for every piece.

The single-piece `auto-replace` command still exists unchanged, for one-off single-slot
replacements. **Verified live** (from an earlier run): `--mesh-selector gloves
--donor-id proxima_ref_hands` against the real Sherwood Huntress archive correctly
selected `Gloves_1.obj`, merged it onto the real 2-submesh `cd_phw_00_hand_00_0146.pac`
hand donor (2,860 -> 23,730 verts, both submeshes preserved), and CrimsonForge rebuilt a
real, loadable 4.6MB `.pac` with a complete 7-file DMM package.

The catalog now also includes 3 new entries sourced from a real, working reference DMM
mod (not yet donor-merge-tested by `sky2cd` beyond the gloves run above, but live-
verified to resolve and parse against the current game install): `proxima_ref_feet`
(`cd_phw_00_foot_0043.pac`), `proxima_ref_hands` (`cd_phw_00_hand_00_0146.pac`, 2
submeshes), and `proxima_ref_head` (`cd_phw_00_hel_00_0146.pac`, 2 submeshes) — giving
donor coverage for the feet/hands/head slots in addition to the existing lower/upper
body donor.

**Real, confirmed constraint (not a bug in `sky2cd` — a genuine PAC format limit),
now auto-fixed:** running this against the real Sherwood Huntress mod against the real
`cd_phw_00_lb_00_0182.pac` donor originally produced a merged mesh with too many
vertices in one submesh (CrimsonForge's own `build_pac()` packs per-submesh vertex
counts into an unsigned 16-bit field, so **65,535 vertices is a hard ceiling**, and
`build_pac()` also requires the rebuilt file to keep the *same number of submeshes*
as the original — so splitting an outfit across new submeshes isn't an option; the
existing submesh(es) really do have to fit the geometry).
`sky2cd auto-replace` now automatically fixes this before it can happen, via
`sky2cd.decimate`:

1. **Weld duplicate vertices** (lossless) — merges vertices whose position, normal,
   UV, *and* bone weights are all identical (within a small rounding tolerance); real
   UV-seam/hard-edge vertices (different normal/UV at a shared position) are untouched.
2. **Quadric-edge-collapse decimation** (lossy, only if welding alone isn't enough) —
   via the `fast_simplification` package (prebuilt wheels, no C++ toolchain needed),
   targeting whatever vertex budget remains after the donor's own real vertex count
   (`65535 - donor_vertices - 500 safety margin`). Each decimated vertex's normal/UV/
   bone weights are copied from its single nearest original vertex (not interpolated).
3. **Grid-based vertex-clustering fallback** (lossy, only if #2 plateaus) — **confirmed
   live**: quadric decimation can get permanently stuck well above the requested
   target regardless of how small the target or how high `agg` is set (a real,
   51,767-vert donor left a ~13,268-vertex budget for a 68,874-vert outfit; quadric
   decimation plateaued at exactly ~54,345/54,353 verts across every retry, even on an
   isolated single mesh island tested down to a target of 10). This is a genuine
   topology-dependent stopping point in that algorithm, not a tuning problem. Grid
   clustering has no such stopping point — merging every vertex that lands in the same
   grid cell always shrinks the count as the grid coarsens, so a bisection search over
   cell size is guaranteed to reach any target — and is applied only to whatever
   quadric decimation already achieved, as a last resort.

Re-run against the real, current game install: the Sherwood Huntress outfit
(68,874 verts after `convert`) needed to fit into only a ~13,268-vertex budget after
the real donor's vertex count grew to 51,767 between test runs (a live Steam game
update). Quadric decimation alone plateaued around 54,345 verts, so the clustering
fallback finished the job, landing the outfit at 3,101 verts, merged into a
54,868-vertex single submesh — safely under the limit — and CrimsonForge's
`build_pac()` produced a real, loadable 11MB `.pac` with no manual intervention.
`sky2cd auto-replace` prints a line (`Outfit was simplified to fit the real PAC vertex
limit: X -> Y vertices`) whenever this kicks in. `--decimation-agg` (default `7.0`)
tunes `fast_simplification`'s starting aggressiveness. If a donor's own vertex count
alone already exceeds the budget, `auto-replace` still fails with a clear message
rather than crashing — picking a lower-vertex-count donor remains the only option for
that specific edge case.

**Also worth noting:** this module's real dependencies are CrimsonForge's own
(`lz4`, `cryptography` — verified from its real `requirements.txt`), installable via
`pip install -e ".[crimsonforge]"`; the prebuilt `.exe`s already bundle them.
`fast_simplification` (used for the vertex-limit fix above) is a regular required
dependency of `sky2cd` itself (prebuilt Windows wheel, no compiler needed).

### Pipeline performance

For large multi-piece outfits (tens of thousands of vertices per piece), the pure-
Python side of the pipeline had a few real bottlenecks, fixed as follows:

- **`weights/sidecar.py` (`reapply_weights`)** — replaced a per-vertex Python `for`
  loop (one `cKDTree.query()` call per vertex) with a two-tier vectorized version: a
  single index-aligned distance check across all vertices at once for exact matches
  (comparing edited vertex *i* only to source vertex *i*, never "the nearest source
  vertex overall" — this specific semantic is locked in by a regression test, since
  two near-duplicate source vertices at different indices must not get confused), then
  one batched `cKDTree.query(..., workers=-1)` call for whatever's left unmatched.
- **`deform/idw.py` / `deform/penetration_fix.py`** — `cKDTree.query(..., workers=-1)`
  now uses all CPU cores per query; `IDWDeformer` caches the source-body `cKDTree`
  per-instance so it's built once and reused across every piece of a multi-piece
  archive run instead of rebuilt from scratch per piece; `fix_penetration()` now
  accepts an optional pre-built tree for the same reason.
- **`pipeline.py`** — builds the shared target-body `cKDTree` once per archive
  conversion and threads it through every piece's `fix_penetration()` call.
- **`exporters/obj_exporter.py`** — replaced per-line Python string building for
  `v`/`vt`/`vn`/`f` lines with bulk vectorized formatting (`np.savetxt` into a
  buffer for vertex/UV/normal rows; a vectorized 1-based triangle formatter for
  faces), and replaced the old $O(\text{submeshes} \times \text{triangles})$ nested
  loop with an $O(\text{triangles})$ stable-sort + `np.searchsorted` grouping —
  while still preserving **first-seen submesh order** (not numeric id order), since
  CrimsonForge's own re-import and `sky2cd`'s multi-submesh donor merges depend on
  that exact ordering. Locked in by a regression test using out-of-order submesh ids.

**Thread-based parallelism across pieces was intentionally skipped**: a thread pool
can't help GIL-bound pure-Python loops, and the Python-side work above is not the
dominant cost anyway.

**Process-based parallelism across pieces was implemented**, because CrimsonForge's
own `build_pac()` full-rebuild step (nearest-vertex skin weight inference + vertex
quantizing/packing per section — external, CrimsonForge-side work sky2cd cannot patch)
dominates real end-to-end time, at roughly 1.5-4 minutes *per piece*, confirmed via
live process CPU monitoring on real multi-piece batch runs. Since each piece's donor
lookup + rebuild is fully independent of every other piece, running pieces concurrently
in separate OS processes gives a real wall-clock win even though the Python-side code
itself isn't the bottleneck:

- `auto_replace_batch_from_skyrim(..., max_workers=...)` accepts an optional
  `max_workers` int: `None`/`1` (the default) preserves the exact original sequential
  code path (loads CrimsonForge/VFS once, processes pieces in a plain loop) with zero
  behavior change. Any other value (a positive int, or `-1` for "use all CPU cores")
  dispatches pieces across a `concurrent.futures.ProcessPoolExecutor`, one worker
  process per piece, via `executor.map()` — which guarantees the results come back in
  the same order the pieces were submitted, regardless of which piece's CrimsonForge
  rebuild finishes first. Each worker process loads its own CrimsonForge/VFS handles
  (these aren't picklable across a process boundary), so there's a small fixed
  per-worker startup cost that's negligible next to multi-minute rebuilds.
- The `auto-replace-all` CLI subcommand exposes this as `--max-workers N` (default
  `1`; pass `-1` to use all cores).
- Because PyInstaller-frozen executables re-execute the whole program when a child
  process is spawned unless guarded, both `cli.py` and `gui.py` call
  `multiprocessing.freeze_support()` as the first statement inside their
  `if __name__ == "__main__":` guard — required for `--max-workers` to work correctly
  in `sky2cd.exe`/`sky2cd-gui.exe` rather than recursively relaunching the CLI in every
  worker process.

All of the above preserve identical output to the prior implementation — verified by
the full test suite (149 passed, 1 skipped) plus new regression tests specifically
targeting the two semantics above (exact-match index alignment, first-seen submesh
order, and order-preserving parallel piece dispatch) that a naive vectorized/parallel
rewrite could otherwise silently break.



If every Skyrim outfit you convert is built on the **same** reference body (e.g. stock
CBBE 3BA/3BBB), and you always target the **same** single Crimson Desert body (e.g.
Fem Kliff), the body-to-body shape difference is a *fixed* deformation field — it does
not depend on which outfit you're converting. `sky2cd`'s `IDWDeformer` already exploits
exactly this: it computes a per-vertex displacement between `source_body` and
`target_body` once, then applies it to any outfit's vertices via inverse-distance
weighting from the nearest body vertices. This can automate a first fitting pass,
but each garment still needs inspection, particularly near joints and loose cloth.

**What this means in practice:** the "one-time Blender/BodySlider work" is sculpting (or
running a BodySlider preset over) your reference body *once* to match the target CD
body's proportions, **keeping the exact same vertex topology and vertex order**.
Equal vertex counts alone are insufficient. Save that validated pair as a preset
to reuse its deformation field; this does not guarantee future garments need no
further fitting.

Use the new `build-preset` CLI command to bake this once:

```
sky2cd build-preset \
  --source-body cbbe_3ba_reference.nif \
  --target-body cbbe_3ba_shaped_to_fem_kliff.nif \
  --name fem_kliff_cbbe \
  --out my_presets/
```

- `--source-body`: your stock CBBE/3BA reference body (`.nif` or `.meshir.json`).
- `--target-body`: the **same mesh**, reshaped/sculpted once to match the Fem Kliff
  (or any other) Crimson Desert body's proportions — same vertex count/order as
  `--source-body`. This is the one-time manual step.
- This writes `fem_kliff_cbbe.json` (+ two `.meshir.json`/`.npz` body files) into
  `my_presets/`. From then on: `sky2cd convert <any outfit> --body-config
  my_presets/fem_kliff_cbbe.json --out out` generates an experimental fit to inspect.

**Caveat that doesn't go away:** this only automates the *body-shape-conforming* step.
The physics-donor-merge and submesh-count reconciliation described above is still
per-outfit manual work, because it depends on each outfit's own topology/submesh
layout, not on the body shape — a fixed body-pair transform can't predict that.

### `sky2cd merge` — merging donor geometry, VERIFIED to enable auto-weight-inference (see section above)

The manual step above (find a donor with working physics, shrink it to hidden, merge
your outfit's geometry on top, reconcile submesh counts) is genuine Blender/3D work.
`sky2cd merge` automates the *geometry-concatenation* mechanics of it:

```
sky2cd merge \
  --donor  donor_item.obj \
  --outfit converted_outfit.obj \
  --out    merged_outfit.obj \
  --shrink 0.02 \
  --submesh-strategy nearest
```

- `--donor`: a donor CD item's `.obj`, exported from **CrimsonForge** (pick one with
  known-working cloth physics, per the Dawnbreaker author's technique above).
- `--outfit`: your converted outfit `.obj` (output of `sky2cd convert`).
- `--shrink`: shrinks the donor's own geometry toward its bounding-box center (default
  `0.02` = shrunk to 2% of its size) instead of deleting it — the geometry stays present
  so anything relying on it (rig/physics binding) still has something to reference.
- `--submesh-strategy`: `nearest` (default) assigns each outfit triangle to whichever of
  the donor's *existing* submeshes has the closest triangle-centroid, keeping the total
  submesh count equal to the donor's — this mirrors the "submesh counts must roughly
  match" pitfall the Dawnbreaker author hit by hand. `append` instead adds the whole
  outfit as one brand-new submesh (simpler, but more likely to need texture/material
  cleanup afterwards).
- Result: one merged `.obj` — geometrically correct, and when re-imported over the
  donor's own `.obj`/`.pac` via CrimsonForge's `build_pac()`, **verified (see section
  above) to inherit real bone weights automatically** for vertices near an already-
  weighted donor region.

**Verified status (tested against the real installed game + real CrimsonForge
source — see the section above for the full test):** feeding this merged `.obj` back
through CrimsonForge's own OBJ-import + `build_pac()` pipeline, against the donor's
real exported `.obj`/`.pac` pair, **does** auto-infer bone weights for the new vertices
via positional-nearest-donor-vertex cloning — no `.cfmeta.json` sidecar needed for this
specific rebuild path. Coverage is only as good as the donor's own weight density.

**Recommended usage:** re-import the merged `.obj` over the donor's own
CrimsonForge-exported `.obj` (same file/header, not a from-scratch file) and run it
through CrimsonForge's `import_obj()` + `build_pac()` against the donor's real `.pac`
bytes. You can still open it in Blender first (optionally alongside the donor imported
via **CrimsonForge's own Blender addon**) if you want to manually touch up any vertices
that land in a sparsely-weighted donor region.

The GUI has a matching "Donor merge" panel with the same fields.

## Experimental or stubbed areas

- **OBJ export — Blender preview/mockup output.** `sky2cd.exporters.obj_exporter.write_obj` writes a standard `.obj`/`.mtl` pair, axis-converted from Skyrim's Z-up to Crimson Desert's Y-up convention. It supports inspection and manual artist work in Blender; it is not itself a fitted, rigged, wearable, or game-ready asset.
- **PAC writer — confirmed non-functional in-game (see above).** `sky2cd.pac.writer.write_pac` emits a single-LOD file with an invented 40-byte vertex stride (quantized position, float16 UV, packed R10G10B10A2 normal, bone indices, bone weights). It round-trips its own format correctly and is unit-tested, and is kept for inspection/debugging, but it does **not** match Crimson Desert's real mesh binary layout. Use the `.obj` output + CrimsonForge instead.
- **NIF importer:** `sky2cd.importers.nif_importer.import_nif` has a clean optional-dependency boundary. If `pynifly` is missing, it raises an informative `ImportError`; real `.nif` extraction still needs validation with actual Skyrim files and the installed importer API.
- **Rigid MLS and BSW deformers:** interfaces are present and intentionally raise `NotImplementedError` with TODO guidance. They are placeholders for future licensed/permission-safe implementations.
- **HKX, cloth, and physics:** not attempted. Pipeline reports include `flagged-rigid-no-physics` so this gap is explicit.
- **BSA and plugin parsing:** `.bsa` game archives and `.esp`/`.esl` plugin files are not parsed directly. Extracted folder structures and `.7z`/`.zip` mod download packages are supported.
- **Drag-and-drop in GUI:** The GUI uses file Browse dialogs. Stdlib tkinter has no native drag-and-drop support (which requires the external `tkdnd`/`tkinterdnd2` extension).
- **Donor merge (`sky2cd merge`) — geometry-concatenation helper, VERIFIED to enable auto-weight-inference on rebuild.** Concatenates a converted outfit onto a shrunk donor item's geometry and reconciles submesh assignment. Tested directly against the real installed game (v2.02.00) + CrimsonForge v1.26.0's real source: re-importing the merged `.obj` over the donor's own exported `.obj`/`.pac` and rebuilding with `build_pac()` clones bone weights from the nearest original donor vertex for new geometry, with no sidecar required. See the dedicated section above for the full test and its limits.
- **tkinter requirement:** the GUI needs a CPython build that includes tcl/tk. Some embeddable/portable Python distributions omit it; in that case `sky2cd-gui` prints an explicit message and exits 1 rather than crashing. `dist\sky2cd-gui.exe` bundles tcl/tk, so it has no such requirement.

## Install and test

```powershell
pip install -e .[dev]
pytest
```

The test suite uses only synthetic meshes. It does not require Skyrim, Crimson Desert, Blender, or `pynifly`.

## Desktop GUI

The GUI opens on **Blender Prep & Preview**. Its advanced DMM packaging tab is optional
and experimental; neither tab certifies a fitted, rigged, or game-ready asset.
The advanced tab includes a **Suggest donor** action: enter a recognizable piece name
such as `Dress_1.nif`, choose a working/output folder, and the GUI displays the top
recommendation, alternates, and reasons in the shared log. It also selects the
recommended catalog entry, writes `donor_suggestion.json`, enables **Open JSON folder**,
and keeps the starting-target/artist-validation boundary visible. This action does not
run conversion, donor export, rebuild, or DMM packaging.

**Dark mode:** the GUI opens in dark mode by default. A **Dark mode** checkbox in the
bottom status bar (next to the status text) toggles the theme immediately, without a
restart, and persists the choice to the same settings file used for other GUI
preferences (`~/.sky2cd/settings.json`, `dark_mode` field). Unchecking it switches to a
light theme; the preference is remembered the next time the GUI opens.

**Hover tooltips & layout:** the most confusing controls (input picker, output folder,
Create Preview Files, Suggest donor, Open JSON folder, the Dark mode toggle, body
preset/custom config, the Manual Donor Merge fields, and the DMM packaging
path/CrimsonForge fields) show a short hover tooltip explaining what they do and,
where relevant, restating that donor suggestions/merges are a starting point only —
e.g. the Manual Donor Merge tooltips explain where the donor `.obj` and outfit `.obj`
come from (a donor export/Blender scene and the `source.obj` from Create Preview
Files, respectively). The window uses a larger, modern flat layout: pill-style tabs,
a bigger default size, section headings, borderless "card" panels (e.g. Game & Tool
Paths), and an accent-colored primary action button, in both light and dark themes.
The tabs area and the status/log panel below are separated by a **draggable
divider** (a thin horizontal bar just above the progress bar) — click and drag it
up or down to give the log more or less room, the same way a resizable panel works
in most modern editors.

```powershell
pip install -e .[dev]
sky2cd-gui              # installed gui-script, no console window
```

Alternatives that need no install step: double-click `sky2cd-gui.pyw`, or build and double-click `dist\sky2cd-gui.exe` (see below). `sky2cd-gui.bat` is an optional convenience launcher that only reports a clear error when the exe has not been built yet.

Window contents:

| Control | Notes |
| --- | --- |
| Skyrim outfit input | Browse for `.7z`, `.zip`, `.nif`, or `.meshir.json` (or Drag & Drop directly onto window) |
| Body config (JSON) | Same file the CLI's `--body-config` takes (or Drag & Drop onto window) |
| Output folder | Created if missing (or Drag & Drop folder onto window) |
| Deformer | `idw` works; `rigid-mls` and `bsw` are labelled **unavailable (not implemented)** and are rejected with a clear message if selected |
| Convert | Runs the pipeline on a background thread; the button is disabled and an indeterminate progress bar animates while it runs |
| Show report / Open output folder | Enabled after a successful run |

- **Drag & Drop:** You can directly drag and drop a `.7z`, `.zip`, `.nif`, or `.meshir.json` file onto the window to automatically populate the outfit input field, a body config JSON onto the window to set the body config, or a folder to set the output destination.

Validation failures (missing file, wrong extension, output path that is a file, stub deformer) produce a specific message in the log and a modal error dialog. Pipeline failures print the exception type, message, and full traceback into the log — nothing is swallowed.

The command-line tool is unchanged; the GUI is purely additive.

## Build standalone Windows executables

Install the build extra and run the PyInstaller wrapper:

```powershell
pip install -e .[dev,build]
.\build_exe.ps1              # builds both exes; -Target cli or -Target gui builds one
dist\sky2cd.exe --help
dist\sky2cd-gui.exe
```

This emits two one-file executables and explicitly bundles `sky2cd\data\slot_mappings.json`, which PyInstaller can otherwise miss:

- `dist\sky2cd.exe` — console subsystem, the CLI.
- `dist\sky2cd-gui.exe` — built with `--windowed`, so it is a Windows GUI-subsystem binary that opens the converter window with **no console window behind it**. This is the double-click deliverable.

### Double-clicking the exe

Prefer `dist\sky2cd-gui.exe` — it is a real windowed application and double-clicking it just works.

`sky2cd.exe` is a command-line tool: it needs arguments (`convert ...` or `report ...`) to do anything. Windows console apps close their window the instant they exit, so double-clicking `sky2cd.exe` with no arguments used to look like it "did nothing and closed immediately."

Two things fix that:

- Running `sky2cd.exe` with no arguments now prints a welcome banner and full usage instead of erroring silently, and (only when launched interactively as a frozen exe) waits for **Enter** before the window closes.
- `sky2cd-launch.bat` at the repo root runs `dist\sky2cd.exe` and always `pause`s afterward, so it is the recommended double-click entry point, especially if you want to pass arguments by editing the `.bat` or dragging a file onto it.

No errors are ever suppressed — this only adds a banner/pause for the empty-argument case and keeps the window open long enough to read any error.

**PyNifly bundling correction + third-party license status (release blocker):** an
earlier version of this note said PyNifly is "not bundled" and must be installed
separately by the user. That is only half true: `sky2cd.importers.nif_importer` also
looks for (and, if present, auto-adds to `sys.path`, including inside a frozen
PyInstaller `.exe` via `_MEIPASS`) a **vendored copy already checked into this repo** at
`src\sky2cd\vendor\io_scene_nifly\` (Bad Dog's PyNifly Blender add-on, including its
native `NiflyDLL.dll`/`hkxcmd.exe`). If that vendored copy is present when `dist\sky2cd.exe`
is built, PyNifly **is** bundled into the executable, contradicting the older wording.
Separately, and more importantly for a public release: **that vendored directory
contains no `LICENSE` file and no license text anywhere in its tree** (confirmed by a
direct search of every file in it) — only a `# Copyright (c) 2021, Bad Dog.` header
comment. PyNifly's real license terms could not be established from what's actually
vendored here. **This is an open release blocker**: do not publicly redistribute
`src\sky2cd\vendor\io_scene_nifly\` (or a `.exe` built with it bundled) until its actual
upstream license is obtained from Bad Dog's own PyNifly repository/release and either
included alongside the vendored copy or the vendored copy is removed in favor of the
user-installs-it-themselves path described below. No license text has been invented or
assumed here.

If you do not use the vendored copy, PyNifly is a Windows Blender add-on with a native `NiflyDLL.dll`, not a PyPI package. `.meshir.json` workflows run standalone; `.nif` import still requires the user to install PyNifly from the GitHub release and expose `io_scene_nifly` on `PYTHONPATH` before launching the executable. If PyNifly is missing or its DLL cannot load, `sky2cd convert input.nif ...` raises the same informative importer error instead of failing silently.

If PyNifly is installed from its GitHub release and you have a legal/test `.nif` file, run the optional importer integration test with:

```powershell
$env:PYNIFLY_TEST_NIF = "C:\path\to\mesh.nif"
pytest tests\test_nif_importer.py
```

## Example body config

`sky2cd convert` expects body data as `MeshIR` files. For `.nif` input, install PyNifly and validate with real files. PyNifly is Windows-only, targets Blender 4+, and is not published as a normal PyPI wheel, so `pip install pynifly` will not work. Download `io_scene_nifly.zip` from the [PyNifly GitHub releases](https://github.com/BadDogSkyrim/PyNifly/releases), extract it, and put the extracted `io_scene_nifly` directory on `PYTHONPATH` or in a `.pth` file for your environment.

```powershell
$site = python -c "import site; print(site.getsitepackages()[0])"
Set-Content "$site\pynifly-addon.pth" "C:\Tools\io_scene_nifly"
pip install -e .[dev]
sky2cd convert C:\Games\Skyrim\Data\meshes\armor\example.nif `
  --body-config body-config.json `
  --deformer idw `
  --out converted
```

Minimal `body-config.json`:

```json
{
  "geometry_mode": "body_fit",
  "source_body": "bodies/source_body.meshir.json",
  "target_body": "bodies/target_body.meshir.json",
  "scale": 1.0,
  "output_scale": 0.0142875,
  "skyrim_slots": ["32"],
  "sidecar": "exports/outfit.cfmeta.json"
}
```

- `scale` is applied to the outfit **before** deformation and must match the coordinate
  system of `source_body`/`target_body` -- it's for cases where the outfit and your
  reference bodies were authored at different scales, not for the Skyrim-to-CD unit
  conversion.
- `output_scale` is applied **after** deformation (or directly to a rigid preview).
  Built-in `0.0142875` is a starting unit estimate, not proof of anatomical alignment
  with the selected CD character. Actor scale, customization, rest pose and origin
  must be checked separately. For already metre-scale references, use `1.0`.
- `geometry_mode: "rigid_preview"` skips references, fitting and collision entirely.
  It can be used without body paths. `body_fit` requires suitable custom references.
- `collision_max_distance` is omitted by default. If supplied, it enables the
  approximate local pass described above; `min_clearance` alone does not enable it.

For test and tooling workflows, `convert` also accepts a `.meshir.json` input directly in place of `.nif`.
