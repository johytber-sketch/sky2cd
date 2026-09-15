"""Metadata-only "Donor Catalog" of known Crimson Desert replacer targets.

**We never bundle donor mesh/texture bytes.** Those are Pearl Abyss's own
copyrighted game assets and stay wherever the user's real Steam install
already has them; this catalog only ships small, human-authored *pointers*
(display name, VFS-relative path, package group, slot, known caveats) plus a
`verify_against_install()` helper that checks each entry still resolves
against the user's own real game files (via CrimsonForge's `VfsManager`)
before it's offered as a browsable choice, since a game patch can move or
rename items between builds.

Every entry currently in `BUILTIN_DONOR_CATALOG` was independently
confirmed this session via a live query of the real, installed game (v2.02.00)
-- not guessed from third-party documentation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DonorEntry:
    """One known, catalog-listed Crimson Desert item usable as a replacer target."""

    id: str
    display_name: str
    slot: str
    entry_path: str
    package_group: str = ""
    dyeable: bool = True
    physics_quality: str = "unknown"  # "verified", "unknown", "none"
    notes: str = ""


BUILTIN_DONOR_CATALOG: tuple[DonorEntry, ...] = (
    DonorEntry(
        id="demenissian_elite_leather_lb",
        display_name="Demenissian Elite Uniform Leather Armor (lowerbody) -- WRONG SLOT FOR BOOTS",
        slot="lowerbody",
        entry_path="character/cd_phw_00_lb_00_0182.pac",
        package_group="0009",
        dyeable=True,
        physics_quality="verified",
        notes="Confirmed real donor: 51,767 verts, real bone-weight inheritance verified "
        "(91.7% of merged vertices) when used as a donor via sky2cd merge + CrimsonForge rebuild. "
        "CAUTION: this is a genuine pants/legwear item (slot='lowerbody'), NOT boots/feet. Cross-"
        "referencing the real game's character-catalog data (core.asset_catalog on the 'phw' family) "
        "confirms item 0182 does not appear in any known character's actual outfit and was mistakenly "
        "used as the donor for a *boots* conversion earlier in this project's history -- that mismatch "
        "is the confirmed root cause of the resulting mod not visibly changing anything in-game. Only "
        "use this entry for genuine lowerbody/pants conversions, never for boots.",
    ),
    DonorEntry(
        id="damian_elite_leather_ub",
        display_name="Damian's Elite Uniform Leather Armor (upperbody/torso)",
        slot="upperbody",
        entry_path="character/cd_phw_00_ub_00_0163.pac",
        package_group="0009",
        dyeable=True,
        physics_quality="verified",
        notes="Corrected item number (was mistakenly 0182; the real game character-catalog record for "
        "the named 'phw' character 'Damian' (app_id cd_phw_00_damian_00000) lists his real armor "
        "meshes as cd_phw_00_ub_00_0163_index01 (this base file, torso) and cd_phw_00_foot_00_0163_"
        "index01 (see damian_elite_leather_boots below, feet) -- confirmed via core.asset_catalog."
        "build_character_catalog_from_vfs against the live game). 15 submeshes, 9,319 verts, bbox "
        "Y 0.73-1.65m (torso-height) -- shape-verified.",
    ),
    DonorEntry(
        id="damian_elite_leather_boots",
        display_name="Damian's Elite Uniform Leather Boots (feet)",
        slot="feet",
        entry_path="character/cd_phw_00_foot_00_0163.pac",
        package_group="0009",
        dyeable=True,
        physics_quality="verified",
        notes="The correct donor for boots conversions matching the torso item above (same item "
        "number 0163, sibling slot). 4 submeshes, 3,184 verts, bbox Y -0.07 to 0.45m (ground/foot-"
        "height) -- shape-verified as boot-shaped, unlike the old (wrong) cd_phw_00_lb_00_0182 pants "
        "donor. Use this entry, with slot='feet', for boots -- not the 'lowerbody' entry above.",
    ),
    DonorEntry(
        id="proxima_ref_feet",
        display_name="Feet item (path reused from a real, working reference DMM mod)",
        slot="feet",
        entry_path="character/cd_phw_00_foot_0043.pac",
        package_group="0009",
        dyeable=True,
        physics_quality="unknown",
        notes="Real, live-verified path (1,348 verts) -- also used as a genuine replacer target "
        "in a real, currently-installed working DMM mod (not just a catalog guess). Not yet "
        "donor-merge-tested end to end by sky2cd itself.",
    ),
    DonorEntry(
        id="proxima_ref_hands",
        display_name="Hands item (path reused from a real, working reference DMM mod)",
        slot="hands",
        entry_path="character/cd_phw_00_hand_00_0146.pac",
        package_group="0009",
        dyeable=True,
        physics_quality="unknown",
        notes="Real, live-verified path (2,860 verts across 2 submeshes) -- also used as a genuine "
        "replacer target in a real, currently-installed working DMM mod. Not yet donor-merge-tested "
        "end to end by sky2cd itself; the 2-submesh layout means merge_onto_donor's 'nearest' "
        "submesh-assignment strategy determines which submesh new geometry lands in.",
    ),
    DonorEntry(
        id="proxima_ref_head",
        display_name="Head/hood item (path reused from a real, working reference DMM mod)",
        slot="head",
        entry_path="character/cd_phw_00_hel_00_0146.pac",
        package_group="0009",
        dyeable=True,
        physics_quality="unknown",
        notes="Real, live-verified path -- also used as a genuine replacer target in a real, "
        "currently-installed working DMM mod. Donor-merge-tested end to end by sky2cd's real "
        "auto-replace/auto-replace-all runs. Vertex/submesh counts for this specific item have been "
        "observed to fluctuate between separate live runs against the same running game install -- "
        "seen as both 1 submesh/15,975 verts and 2 submeshes/7,849 verts within the same session -- "
        "so treat any single recorded count here as a snapshot, not a fixed fact; the same drift "
        "pattern has already been observed for other donors in this catalog.",
    ),
)



def list_catalog() -> list[DonorEntry]:
    """Return the built-in donor catalog as a plain list."""
    return list(BUILTIN_DONOR_CATALOG)


def get_entry(entry_id: str) -> DonorEntry:
    """Look up a catalog entry by its `id`. Raises `KeyError` if not found."""
    for entry in BUILTIN_DONOR_CATALOG:
        if entry.id == entry_id:
            return entry
    raise KeyError(f"No donor catalog entry with id '{entry_id}'")


@dataclass(frozen=True)
class DonorVerificationResult:
    entry: DonorEntry
    found: bool
    resolved_package_group: str = ""
    error: str = ""


def verify_against_install(vfs, entries: list[DonorEntry] | None = None) -> list[DonorVerificationResult]:
    """Check each catalog entry still resolves against a real, open game VFS.

    `vfs` is a `CrimsonForge` `VfsManager` instance (see
    `sky2cd.crimsonforge_bridge.open_vfs`). Entries that no longer resolve
    (e.g. after a game patch moved/renamed the file) are reported with
    `found=False` rather than raising, so the caller can filter a "Browse
    Donors" list down to only what's actually usable on this install.
    """
    from sky2cd.crimsonforge_bridge import find_donor_entry

    results: list[DonorVerificationResult] = []
    for entry in entries if entries is not None else BUILTIN_DONOR_CATALOG:
        try:
            group, _ = find_donor_entry(vfs, entry.entry_path, entry.package_group)
            results.append(DonorVerificationResult(entry=entry, found=True, resolved_package_group=group))
        except FileNotFoundError as exc:
            results.append(DonorVerificationResult(entry=entry, found=False, error=str(exc)))
    return results
