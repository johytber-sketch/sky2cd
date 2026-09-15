"""Evidence-based donor recommendations for artist-assisted Blender work."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile

import numpy as np

from sky2cd import crimsonforge_bridge as cfb
from sky2cd.donor_auto_select import guess_slot_from_path
from sky2cd.donor_catalog import DonorEntry, list_catalog, verify_against_install
from sky2cd.meshir import MeshIR, load_meshir

RECOMMENDATION_BOUNDARY = (
    "This recommendation is only a practical Blender/game starting target. "
    "It does not guarantee fit, clipping safety, rig or weight correctness, "
    "animation safety, or a finished wearable/game-ready conversion."
)


@dataclass(frozen=True)
class DonorEvidence:
    """Optional evidence gathered from the user's live game install."""

    verified: bool | None = None
    resolved_package_group: str = ""
    ingame_name: str | None = None
    sidecar_paths: tuple[str, ...] = ()
    bounds_compatibility: float | None = None
    inspection_error: str = ""

    @property
    def has_material_sidecar(self) -> bool:
        return any(path.lower().endswith(".pac_xml") for path in self.sidecar_paths)

    @property
    def texture_count(self) -> int:
        return sum(path.lower().endswith(".dds") for path in self.sidecar_paths)


@dataclass(frozen=True)
class DonorRecommendation:
    entry: DonorEntry
    score: float
    reasons: tuple[str, ...]
    evidence: DonorEvidence

    @property
    def display_name(self) -> str:
        return self.evidence.ingame_name or self.entry.display_name


def bounds_compatibility(source: MeshIR, donor: MeshIR) -> float | None:
    """Compare scale-independent bounding-box proportions in the range 0..1."""
    source_extents = np.ptp(source.positions, axis=0)
    donor_extents = np.ptp(donor.positions, axis=0)
    if not np.all(np.isfinite(source_extents)) or not np.all(np.isfinite(donor_extents)):
        return None
    if float(source_extents.max()) <= 0.0 or float(donor_extents.max()) <= 0.0:
        return None
    source_shape = np.sort(source_extents / source_extents.max())
    donor_shape = np.sort(donor_extents / donor_extents.max())
    distance = float(np.mean(np.abs(source_shape - donor_shape)))
    return max(0.0, min(1.0, 1.0 - distance))


def rank_donors(
    piece_name: str,
    *,
    catalog: list[DonorEntry] | None = None,
    evidence_by_id: dict[str, DonorEvidence] | None = None,
    inferred_slot: str | None = None,
) -> list[DonorRecommendation]:
    """Rank same-slot donors using catalog and optional live-install evidence."""
    slot = inferred_slot or guess_slot_from_path(piece_name)
    if slot is None:
        raise ValueError(
            f"Could not infer an equipment slot from {piece_name!r}. "
            "Use a piece filename containing a recognizable term such as boots, gloves, hood, dress, torso, or pants."
        )

    evidence_by_id = evidence_by_id or {}
    candidates = [entry for entry in (catalog if catalog is not None else list_catalog()) if entry.slot == slot]
    if not candidates:
        raise ValueError(f"No catalog donors match the inferred '{slot}' slot for {piece_name!r}.")
    if evidence_by_id and all(entry.id in evidence_by_id for entry in candidates):
        verified_candidates = [
            entry for entry in candidates if evidence_by_id.get(entry.id, DonorEvidence()).verified is True
        ]
        if verified_candidates:
            candidates = verified_candidates
        elif all(evidence_by_id.get(entry.id, DonorEvidence()).verified is False for entry in candidates):
            raise ValueError(
                f"No '{slot}' donor candidates were found in the supplied live game install."
            )

    ranked: list[DonorRecommendation] = []
    for entry in candidates:
        evidence = evidence_by_id.get(entry.id, DonorEvidence())
        score = 100.0
        reasons = [f"matching {slot} slot"]

        if evidence.bounds_compatibility is not None:
            score += evidence.bounds_compatibility * 30.0
            quality = "strong" if evidence.bounds_compatibility >= 0.8 else "moderate"
            reasons.append(f"{quality} bounds-shape compatibility")
        if evidence.verified is True:
            score += 20.0
            reasons.append("live game source verified")
        elif evidence.verified is False:
            score -= 100.0
            reasons.append("missing from this game install")
        if evidence.has_material_sidecar:
            score += 12.0
            reasons.append("material sidecar found")
        elif evidence.verified is True:
            score -= 12.0
            reasons.append("required material sidecar not found")
        if evidence.texture_count:
            score += min(6.0, float(evidence.texture_count))
            reasons.append(f"{evidence.texture_count} texture sidecar(s) found")
        if evidence.ingame_name:
            score += 4.0
            reasons.append("in-game display name resolved")
        if entry.physics_quality == "verified":
            score += 8.0
            reasons.append("catalog provenance/physics evidence verified")
        elif "working reference DMM mod" in entry.notes:
            score += 4.0
            reasons.append("known working-reference provenance")
        if evidence.inspection_error:
            reasons.append(f"live mesh inspection unavailable: {evidence.inspection_error}")

        ranked.append(DonorRecommendation(entry, score, tuple(reasons), evidence))

    return sorted(ranked, key=lambda item: (-item.score, item.entry.id))


def load_piece_mesh(path: str | Path) -> MeshIR | None:
    """Load bounds from supported single-piece formats; names alone return ``None``."""
    piece_path = Path(path)
    if not piece_path.is_file():
        return None
    if piece_path.suffix.lower() == ".obj":
        from sky2cd.importers.obj_importer import read_obj

        return read_obj(piece_path)
    if piece_path.suffix.lower() == ".nif":
        from sky2cd.importers.nif_importer import import_nif

        return import_nif(piece_path)
    if piece_path.suffix.lower() == ".json":
        return load_meshir(piece_path)
    return None


def gather_live_evidence(
    piece: str | Path,
    entries: list[DonorEntry],
    *,
    cf,
    vfs,
) -> dict[str, DonorEvidence]:
    """Reuse CrimsonForge/catalog services to inspect candidates against a live install."""
    source_mesh = load_piece_mesh(piece)
    verification = {result.entry.id: result for result in verify_against_install(vfs, entries)}
    resolver = cfb.build_item_name_resolver(cf, vfs)
    gathered: dict[str, DonorEvidence] = {}

    with tempfile.TemporaryDirectory(prefix="sky2cd-donor-suggest-") as temp_dir:
        for entry in entries:
            result = verification[entry.id]
            sidecar_paths: tuple[str, ...] = ()
            compatibility: float | None = None
            inspection_error = ""
            ingame_name = resolver.resolve(entry.entry_path) if result.found else None
            if result.found:
                sidecar_paths = tuple(
                    sidecar.path
                    for sidecar in cfb.find_sidecar_files(vfs, entry.entry_path, result.resolved_package_group)
                )
                if source_mesh is not None:
                    try:
                        pac_bytes = cfb.read_donor_pac_bytes(
                            vfs, entry.entry_path, result.resolved_package_group
                        )
                        donor_obj = cfb.export_donor_obj(cf, pac_bytes, entry.entry_path, temp_dir)
                        from sky2cd.importers.obj_importer import read_obj

                        compatibility = bounds_compatibility(source_mesh, read_obj(donor_obj))
                    except (ImportError, ValueError, FileNotFoundError, RuntimeError) as exc:
                        inspection_error = str(exc)

            gathered[entry.id] = DonorEvidence(
                verified=result.found,
                resolved_package_group=result.resolved_package_group,
                ingame_name=ingame_name,
                sidecar_paths=sidecar_paths,
                bounds_compatibility=compatibility,
                inspection_error=inspection_error,
            )
    return gathered


def format_recommendations(
    piece_name: str,
    recommendations: list[DonorRecommendation],
    *,
    limit: int = 3,
) -> str:
    """Render a concise recommendation plus alternates and the safety boundary."""
    if limit < 1:
        raise ValueError("--limit must be at least 1")
    shown = recommendations[:limit]
    top = shown[0]
    lines = [
        f"Recommended donor: {top.display_name} -- {', '.join(top.reasons)}.",
        f"  donor id: {top.entry.id}",
        f"  path: {top.entry.entry_path}",
    ]
    if len(shown) > 1:
        lines.append("Alternates:")
        for candidate in shown[1:]:
            lines.append(
                f"  - {candidate.display_name} [{candidate.entry.id}] -- "
                f"{', '.join(candidate.reasons)}."
            )
    lines.extend(
        [
            "",
            "Artist-validation boundary: this recommendation is only a practical Blender/game starting target.",
            "It does not guarantee fit, clipping safety, rig or weight correctness, animation safety,",
            "or a finished wearable/game-ready conversion.",
        ]
    )
    return "\n".join(lines)


def recommendation_payload(
    piece_name: str,
    recommendations: list[DonorRecommendation],
    *,
    limit: int = 3,
    inferred_slot: str | None = None,
) -> dict:
    """Serialize ranked recommendations without duplicating ranking logic."""
    if limit < 1:
        raise ValueError("--limit must be at least 1")
    if not recommendations:
        raise ValueError("At least one donor recommendation is required")

    def serialize(item: DonorRecommendation, rank: int) -> dict:
        evidence = item.evidence
        return {
            "rank": rank,
            "score": round(item.score, 6),
            "donor_id": item.entry.id,
            "catalog_display_name": item.entry.display_name,
            "ingame_display_name": evidence.ingame_name,
            "display_name": item.display_name,
            "slot": item.entry.slot,
            "entry_path": item.entry.entry_path,
            "package_group": evidence.resolved_package_group or item.entry.package_group,
            "reasons": list(item.reasons),
            "signals": {
                "live_source_verified": evidence.verified,
                "bounds_compatibility": evidence.bounds_compatibility,
                "material_sidecar_found": evidence.has_material_sidecar,
                "texture_sidecar_count": evidence.texture_count,
                "sidecar_paths": list(evidence.sidecar_paths),
                "ingame_name_resolved": evidence.ingame_name is not None,
                "catalog_physics_quality": item.entry.physics_quality,
                "catalog_dyeable": item.entry.dyeable,
                "inspection_error": evidence.inspection_error or None,
            },
        }

    shown = recommendations[:limit]
    serialized = [serialize(item, rank) for rank, item in enumerate(shown, start=1)]
    return {
        "schema_version": 1,
        "input_piece": piece_name,
        "inferred_slot": inferred_slot or guess_slot_from_path(piece_name),
        "recommended_donor_id": serialized[0]["donor_id"],
        "recommended": serialized[0],
        "alternates": serialized[1:],
        "artist_validation_boundary": RECOMMENDATION_BOUNDARY,
    }


def write_recommendation_json(
    path: str | Path,
    piece_name: str,
    recommendations: list[DonorRecommendation],
    *,
    limit: int = 3,
    inferred_slot: str | None = None,
) -> Path:
    """Write the canonical recommendation payload as UTF-8 JSON."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            recommendation_payload(
                piece_name,
                recommendations,
                limit=limit,
                inferred_slot=inferred_slot,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    return output_path
