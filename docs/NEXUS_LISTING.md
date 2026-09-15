# Nexus Mods listing guide

This document is the reference copy for Sky2Cd's Nexus Mods page. It exists
so the Nexus-facing wording stays consistent with this repository and stays
honest about scope. It is **not** auto-published anywhere — copy/paste the
relevant section into the Nexus page description editor by hand when
creating or updating the listing.

## What to attach on Nexus

**Attach only `sky2cd-gui.exe`.** Do not upload `sky2cd.exe` (the
command-line tool) to Nexus. The CLI stays a GitHub-only, advanced/scripted-use
artifact — see [`docs/USER_GUIDE.md`](USER_GUIDE.md) and the main
[`README.md`](../README.md) for where to get it and how it's used.

Rationale: the GUI is a complete, self-contained double-click experience for
the audience Nexus serves. Offering the CLI there too would suggest it's a
required or equally supported download for typical users, which it is not.

## Suggested Nexus page "Requirements" section

- Windows 10/11, 64-bit.
- No Python install required — `sky2cd-gui.exe` is a self-contained,
  single-file build.
- Blender, installed separately, to open and work with the preview geometry
  Sky2Cd produces. Sky2Cd does not install, launch, or embed Blender.
- Optional, only for live donor verification / resolved in-game names /
  Advanced DMM Packaging: a Crimson Desert install and a separate CrimsonForge
  install. Not required for the primary Blender Prep & Preview workflow.

## Suggested Nexus page description (BBCode-ready plain text)

Copy the paragraphs below into the Nexus description editor, applying Nexus's
own bold/heading formatting as desired. Wording deliberately matches this
repository's honest-boundary language; do not add unsupported claims when
adapting it.

---

**Sky2Cd — Blender outfit toolkit**

Sky2Cd is a Blender preparation toolkit for artist-assisted Skyrim outfit
work. It converts an outfit's source geometry into a preview/mockup you
inspect and develop manually in Blender, and it can suggest a ranked donor
starting point so you don't have to guess cryptic in-game item IDs by hand.

**Download:** grab `sky2cd-gui.exe` below. It is a single, self-contained
file — no Python install needed. Double-click it to launch.

**What it does:**
- Converts a Skyrim outfit's geometry into a Blender-ready preview/mockup.
- Suggests a ranked donor candidate for a piece, with plain-language reasons,
  right in the app, plus a `donor_suggestion.json` file you can keep with
  your work.
- Optionally packages an already artist-rebuilt asset for further use
  (Advanced DMM Packaging tab) — optional and experimental.

**What it does not do:**
- It does not automatically fit a body, correct clipping, transfer or paint
  rig weights, or certify animation safety.
- A donor suggestion is a starting point for your own review — never a
  guarantee of fit, clipping safety, rig/weight correctness, animation
  safety, or a finished wearable/game-ready result.
- Advanced DMM Packaging's structural checks (sidecar presence, provenance
  hashes) are not fit or gameplay validation.
- This page does not distribute the command-line version of sky2cd. Advanced
  users who want the CLI can find it on the project's GitHub releases page.

**Requirements:** Windows 10/11 (64-bit). Blender, installed separately, to
open the preview files. A Crimson Desert install + CrimsonForge are optional
and only needed for live donor verification or Advanced DMM Packaging.

---

## Keeping this in sync

If the GUI gains a new primary control, tooltip category, or honest-boundary
wording change, update this file's "description" section alongside
`README.md`'s GUI section and `docs/USER_GUIDE.md`, then manually re-copy the
updated text into the live Nexus listing — this file is a reference, not a
synced template.
