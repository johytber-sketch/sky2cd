# Placeholder-only Blender walkthrough

This walkthrough names **no bundled game or mod assets**. Replace every
`<PLACEHOLDER>` with a path to a file you are permitted to use.

## 1. Prepare a Blender handoff

```powershell
sky2cd blender-handoff `
  --input "C:\path\to\<YOUR_OWN_DRESS_PIECE>.nif" `
  --piece "dress=damian_elite_leather_ub" `
  --out "C:\path\to\<WORK_FOLDER>"
```

Open `<WORK_FOLDER>\handoff\import_script.py` in Blender. Each piece directory
contains:

- `source.obj`: geometry/axis **preview only**;
- `metadata.json`: conversion notes and explicit limitations;
- `donor_suggestion.json`: ranked donor starting points with evidence and
  alternates.

The handoff does not fit the garment, fix clipping, assign a valid native rig
or weights, validate animation, or create a wearable/game-ready result. Those
remain artist tasks.

## 2. Inspect donor recommendations separately

For quick terminal output:

```powershell
sky2cd donors --suggest "<YOUR_OWN_DRESS_PIECE>.nif"
```

To keep the same machine-readable recommendation beside your work:

```powershell
sky2cd donors `
  --suggest "<YOUR_OWN_DRESS_PIECE>.nif" `
  --suggest-out "C:\path\to\<WORK_FOLDER>\donor_suggestion.json"
```

The JSON contains the inferred slot, top recommendation, alternates, scores,
reasons, and available verification signals. It is a starting target only,
not a fit, clipping, rig, animation, wearable, or game-readiness guarantee.

## 3. Optionally add live donor evidence

This step requires the user's own Crimson Desert installation and a separate
CrimsonForge installation. Neither is bundled.

```powershell
sky2cd donors `
  --suggest "C:\path\to\<YOUR_OWN_DRESS_PIECE>.nif" `
  --packages-path "C:\path\to\<YOUR_GAME_PACKAGES>" `
  --crimsonforge-home "C:\path\to\<CRIMSONFORGE>" `
  --suggest-out "C:\path\to\<WORK_FOLDER>\donor_suggestion_live.json"
```

Live evidence may add source verification, material/texture sidecar presence,
an in-game display name, and bounds-shape compatibility when both meshes can
be read. These signals improve ranking; they do not validate the result.

## 4. Perform and validate the artist work

In Blender, inspect topology and scale, fit the garment, resolve clipping,
review materials, transfer or paint weights against the correct native rig,
and test poses/animations. Rebuild through the appropriate external tooling,
then independently validate the rebuilt asset.

## 5. Optionally package an already validated PAC

Only after the artist has rebuilt and validated the PAC:

```powershell
sky2cd package-dmm --strict `
  --pac "C:\path\to\<ARTIST_REBUILT>.pac" `
  --entry-path "character/<TARGET_PATH>.pac" `
  --sidecar "character/<TARGET_PATH>.pac_xml=C:\path\to\<ARTIST_REBUILT>.pac_xml" `
  --title "<YOUR_MOD_TITLE>" `
  --out "C:\path\to\<PACKAGE_OUTPUT>"
```

Strict mode checks packaging structure, sidecar presence, provenance hashes,
and optional parseability. It still does not validate fit, clipping,
rig/weights, animation safety, wearable output, or game-ready behavior.
