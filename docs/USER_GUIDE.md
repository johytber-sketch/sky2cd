# sky2cd user guide

A practical, no-hype guide to installing and using sky2cd. For a shorter
placeholder-only walkthrough, see [`EXAMPLE_WORKFLOW.md`](EXAMPLE_WORKFLOW.md).
For licensing details and the current release blocker, see
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

## What sky2cd is

A Blender-first preparation toolkit for artist-assisted Skyrim-to-Crimson-Desert
outfit work. It converts an outfit's source geometry into a preview/mockup you
inspect and develop manually in Blender, and it can rank donor candidates so
you don't have to guess cryptic catalog IDs by hand.

## What sky2cd is not

- Not an automatic Skyrim-outfit-to-game-ready-Crimson-Desert converter.
- Not a body-fitting, clipping-correction, or weight-painting tool — those
  remain manual artist steps in Blender.
- Not a rig transplant or animation-safety checker.
- Not a guarantee that any output — Blender preview, donor suggestion, or a
  packaged `.pac` — is wearable or game-ready. Every stage says so explicitly
  in its own output.

## Download and install

Two standalone Windows executables are attached to each
[GitHub release](https://github.com/johytber-sketch/sky2cd/releases):

| File | What it is |
| --- | --- |
| `sky2cd-gui.exe` | Desktop GUI, no console window |
| `sky2cd.exe` | Command-line tool |

Both are single-file builds that already contain the Python interpreter and
every Python dependency. **You do not need to install Python separately to
run either exe.**

Requirements to just run the exes:
- 64-bit Windows 10 or 11.
- No separate Python install, no `pip install`.

Requirements only for specific optional steps (see below), not for launching
the tool itself:
- **Blender**, to actually open and work with the preview geometry sky2cd
  produces. sky2cd never launches or embeds Blender.
- **A Crimson Desert install and a separate CrimsonForge install**, only for
  live donor verification, resolved in-game display names, and Advanced DMM
  Packaging. The core Blender Prep & Preview workflow works fully without
  either.

If you'd rather run from source (developers, or if you want to modify the
tool): `pip install -e .[dev]` then `sky2cd-gui` or `sky2cd --help`. See the
main [`README.md`](../README.md) for the full install/build instructions.

### Windows SmartScreen

Since these executables aren't code-signed, Windows SmartScreen may show
"Windows protected your PC" the first time you run a freshly downloaded exe.
This is standard for unsigned indie tools, not a sign of a virus. If you trust
the source, click **More info → Run anyway**. Only do this for the exe you
downloaded directly from this project's GitHub releases page.

## First launch

Double-click `sky2cd-gui.exe`. The window opens on the **Blender Prep &
Preview** tab, in **dark mode by default**. A **🌙 Dark mode** checkbox in the
bottom status bar toggles the theme immediately (no restart needed) and
remembers your choice in `~/.sky2cd/settings.json` for next time.

If you see nothing change after relaunching a newly downloaded/rebuilt exe,
fully close every existing Sky2CD window first — an old window left open from
before can look identical to a new one and hide any update.

## The GUI at a glance

- **Blender Prep & Preview** (primary tab): input picker, body preset/custom
  config, output folder, deformer choice, and **Create Preview Files**.
- **Advanced DMM Packaging (Experimental)** (secondary tab): donor
  suggestion, optional live game/CrimsonForge paths, and packaging controls —
  intentionally visually secondary to the Blender tab.
- **Hover tooltips** on the most confusing controls (input picker, output
  folder, Create Preview Files, Suggest donor, Open JSON folder, Dark mode
  toggle, body preset/custom config, the Manual Donor Merge fields, and the
  DMM/CrimsonForge path fields) explain what each one does and, where
  relevant, restate that donor suggestions/merges are a starting point only.
- **Draggable log panel:** the tabs area and the status/log panel below are
  split by a divider you can drag up or down for more or less log room.
- **Status badges/wording** throughout call out *preview only*, *donor
  suggested*, *artist validation required*, and *DMM packaging optional* so
  preview output is never confused with a finished result.

## Step-by-step: Blender Prep & Preview (the main path)

1. Launch `sky2cd-gui.exe` (or `sky2cd blender-handoff` from the command
   line — see below).
2. Browse to (or drag-and-drop) your outfit's `.nif`, `.7z`, `.zip`, or
   `.meshir.json` file as the input.
3. Pick a body preset, or browse to a custom body config JSON if you have
   one.
4. Choose or accept the default output folder.
5. Click **Create Preview Files**.
6. Open the generated `handoff\import_script.py` (or the single-piece
   `source.obj`) in Blender.
7. In Blender: inspect topology and scale, fit the garment to the target
   body, resolve clipping, review materials, transfer or paint weights
   against the correct native rig, and test poses/animations. sky2cd does
   not do any of this for you.

Command-line equivalent:

```powershell
sky2cd blender-handoff --input outfit.zip --out .\handoff_out
```

Each piece folder under `handoff_out\handoff\` contains:
- `source.obj` — geometry/axis preview only, not a finished asset.
- `metadata.json` — conversion notes and explicit limitations.
- `donor_suggestion.json` — a ranked donor starting point, if one is
  available for that piece (see next section).

## Donor suggestion (optional, removes ID-guessing pain)

Instead of manually decoding cryptic donor catalog IDs, ask for a ranked
recommendation. This is entirely optional and never required for the
Blender-first workflow above.

**Terminal, quick read:**

```powershell
sky2cd donors --suggest Dress_1.nif
```

```
Recommended donor: Damian's Elite Uniform Leather Armor (upperbody/torso) -- matching upperbody slot, catalog provenance/physics evidence verified.
  donor id: damian_elite_leather_ub
  path: character/cd_phw_00_ub_00_0163.pac

Artist-validation boundary: this recommendation is only a practical Blender/game starting target.
It does not guarantee fit, clipping safety, rig or weight correctness, animation safety,
or a finished wearable/game-ready conversion.
```

**JSON, kept next to your files:**

```powershell
sky2cd donors --suggest Dress_1.nif --suggest-out .\donor_suggestion.json
```

The JSON includes the input piece, inferred slot, recommended donor id,
resolved display/in-game name if available, entry path, score/rank, reasons,
alternates, verification/source signals, and the same explicit boundary text
as the terminal output.

`blender-handoff` also writes `donor_suggestion.json` automatically beside
each recognizable piece's `source.obj`/`metadata.json`, so the recommendation
travels with your Blender handoff files without an extra step.

In the GUI, the **Suggest donor** button (Advanced DMM Packaging tab) does the
same thing: it prints the recommendation and reasons to the shared log,
selects the recommended catalog entry, writes `donor_suggestion.json`, and
enables **Open JSON folder** next to it.

**Ranking signals used, when available:** slot match, mesh/bounds/coverage
compatibility, clean vanilla catalog provenance/verification, required
sidecar/material availability, and a resolved in-game display name. A
recommendation is always a starting point for artist review — never a
guarantee of fit, clipping safety, rig/weight correctness, animation safety,
or a finished wearable/game-ready conversion.

## Optional: live donor verification

Adding real game/tool paths to `--suggest` (or the GUI's path fields)
strengthens the same recommendation with live evidence — it does not change
what the recommendation promises:

```powershell
sky2cd donors --suggest Dress_1.nif `
  --packages-path "C:\...\steamapps\common\Crimson Desert" `
  --crimsonforge-home "C:\path\to\CrimsonForge"
```

This can add: confirmed live source verification, material/texture sidecar
presence, a resolved in-game display name, and bounds-shape compatibility
(only when both meshes are readable). Both a Crimson Desert install and a
separate CrimsonForge install are required for this step and are never
bundled with sky2cd.

## Optional: Advanced DMM Packaging

Only after an artist has independently rebuilt and validated a `.pac` outside
sky2cd:

```powershell
sky2cd package-dmm --strict `
  --pac "C:\path\to\<ARTIST_REBUILT>.pac" `
  --entry-path "character/<TARGET_PATH>.pac" `
  --sidecar "character/<TARGET_PATH>.pac_xml=C:\path\to\<ARTIST_REBUILT>.pac_xml" `
  --title "<YOUR_MOD_TITLE>" `
  --out "C:\path\to\<PACKAGE_OUTPUT>"
```

`--strict` checks packaging structure: sidecar presence, provenance hashes,
and optional parseability. This is a structural packaging check, **not** fit,
clipping, rig/weight, or animation validation, and it does not certify a
wearable or game-ready result. Never source a "donor" `.pac`/`.pac_xml` by
copying it out of an already-installed third-party mod's files — export
donors fresh from your own verified game install instead.

## Troubleshooting

**"Python was not found" / it tries to open the Microsoft Store.**
You're running a source checkout without the exe. Either build/download the
standalone `.exe` (no Python needed), or install Python and run
`pip install -e .[dev]` first.

**Nothing changed after I re-downloaded/rebuilt the GUI exe.**
Fully close every open Sky2CD window before relaunching. A leftover window
from an earlier run looks identical to a new one and can make an update seem
like it didn't apply. On Windows you can confirm no copies are running via
Task Manager (look for `sky2cd-gui.exe`).

**Windows SmartScreen blocked the exe.**
See the SmartScreen note above — click **More info → Run anyway** only if you
trust the source.

**Blender isn't installed / I don't have it yet.**
The Blender Prep & Preview step still produces `source.obj` and
`metadata.json` without Blender installed — you just need Blender separately
to open and work with them. sky2cd does not install or require Blender to run.

**I don't have a CrimsonForge or game `packages` folder configured.**
That's fine for the primary Blender workflow — leave those fields empty. They
are only needed for live donor verification, resolved in-game names, and
Advanced DMM Packaging.

**A `.nif` file fails to import with a PyNifly-related error.**
See the PyNifly section in `README.md` — this project vendors a copy of
PyNifly but its exact license/source-revision provenance is an open
release-blocker item (GPL-3.0 license text is present, but source-commit
correspondence for the bundled DLL is not yet verified — see
`THIRD_PARTY_NOTICES.md`). If PyNifly can't load, the importer raises a clear
error instead of failing silently; you can also install PyNifly yourself from
its GitHub release and put it on `PYTHONPATH`.

## Limitations, stated plainly

- No automatic body fitting.
- No automatic clipping correction.
- No automatic rig or weight transfer.
- No animation-safety certification.
- No claim that any output — Blender preview, donor suggestion, or a
  packaged `.pac` — is a finished, wearable, or game-ready asset.
- Donor suggestions are ranked starting points based on available signals
  (slot, provenance, coverage, sidecars, resolved names) — never a fit,
  clipping, rig, or animation guarantee.
- DMM packaging's `--strict` checks are structural (sidecars, hashes,
  parseability) — not fit or gameplay validation.
- PyNifly's exact license/source-revision provenance for the vendored DLL is
  unresolved; see `THIRD_PARTY_NOTICES.md` before any public redistribution
  decision involving that component.
