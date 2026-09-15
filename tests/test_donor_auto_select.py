"""Tests for `sky2cd.donor_auto_select`: guessing a piece's Crimson Desert
slot from its filename and resolving it against a donor catalog.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sky2cd.donor_auto_select import auto_select_donors, guess_slot_from_path
from sky2cd.donor_catalog import DonorEntry
from sky2cd.donor_recommendation import (
    DonorEvidence,
    bounds_compatibility,
    format_recommendations,
    gather_live_evidence,
    recommendation_payload,
    rank_donors,
    write_recommendation_json,
)
from sky2cd.donor_catalog import DonorVerificationResult
from sky2cd.meshir import MeshIR


def test_guess_slot_from_path_recognizes_common_skyrim_piece_names():
    assert guess_slot_from_path("Gloves_1.nif") == "hands"
    assert guess_slot_from_path("Boots_1.meshir.json") == "feet"
    assert guess_slot_from_path("Hood_1.nif") == "head"
    assert guess_slot_from_path("Dress_1.nif") == "upperbody"
    assert guess_slot_from_path("MyOutfit/UpperBody.nif") == "upperbody"
    assert guess_slot_from_path("MyOutfit/LowerBody.nif") == "lowerbody"


def test_guess_slot_from_path_returns_none_for_unrecognized_filenames():
    assert guess_slot_from_path("weird_file_name_123.nif") is None


def _small_catalog() -> list[DonorEntry]:
    return [
        DonorEntry(id="feet_a", display_name="Feet A", slot="feet", entry_path="character/feet_a.pac"),
        DonorEntry(id="hands_a", display_name="Hands A", slot="hands", entry_path="character/hands_a.pac"),
        DonorEntry(id="head_a", display_name="Head A", slot="head", entry_path="character/head_a.pac"),
        DonorEntry(id="head_b", display_name="Head B", slot="head", entry_path="character/head_b.pac"),
    ]


def test_auto_select_donors_resolves_unambiguous_single_candidate_slots():
    guesses = auto_select_donors(["Boots_1.nif", "Gloves_1.nif"], catalog=_small_catalog())

    assert [g.guessed_slot for g in guesses] == ["feet", "hands"]
    assert [g.resolved.id for g in guesses] == ["feet_a", "hands_a"]
    assert all(not g.ambiguous and not g.unmatched for g in guesses)


def test_auto_select_donors_flags_multiple_candidates_as_ambiguous_not_a_guess():
    [guess] = auto_select_donors(["Hood_1.nif"], catalog=_small_catalog())

    assert guess.guessed_slot == "head"
    assert guess.ambiguous is True
    assert guess.resolved is None
    assert {c.id for c in guess.candidates} == {"head_a", "head_b"}


def test_auto_select_donors_flags_unrecognized_filenames_and_uncataloged_slots_as_unmatched():
    guesses = auto_select_donors(["weird_name.nif", "Dress_1.nif"], catalog=_small_catalog())

    weird, dress = guesses
    assert weird.guessed_slot is None
    assert weird.unmatched is True
    assert weird.resolved is None

    # "upperbody" is a valid guess but this small test catalog has no entry for it.
    assert dress.guessed_slot == "upperbody"
    assert dress.unmatched is True
    assert dress.resolved is None


def test_rank_donors_prefers_verified_compatible_candidate_with_sidecars_and_name():
    catalog = [
        DonorEntry(
            id="feet_catalog_only",
            display_name="Catalog Feet",
            slot="feet",
            entry_path="character/feet_catalog_only.pac",
            physics_quality="verified",
        ),
        DonorEntry(
            id="feet_live",
            display_name="Cryptic Feet",
            slot="feet",
            entry_path="character/feet_live.pac",
            physics_quality="unknown",
        ),
    ]
    evidence = {
        "feet_live": DonorEvidence(
            verified=True,
            ingame_name="Leather Boots of Earth's Honor",
            sidecar_paths=("character/feet_live.pac_xml", "character/feet_live_n.dds"),
            bounds_compatibility=0.92,
        )
    }

    ranked = rank_donors("Boots_1.nif", catalog=catalog, evidence_by_id=evidence)

    assert ranked[0].entry.id == "feet_live"
    assert ranked[0].display_name == "Leather Boots of Earth's Honor"
    assert "matching feet slot" in ranked[0].reasons
    assert "strong bounds-shape compatibility" in ranked[0].reasons
    assert "material sidecar found" in ranked[0].reasons
    assert "live game source verified" in ranked[0].reasons


def test_rank_donors_excludes_candidates_missing_from_live_install():
    catalog = [
        DonorEntry(id="missing", display_name="Missing", slot="feet", entry_path="character/missing.pac"),
        DonorEntry(id="found", display_name="Found", slot="feet", entry_path="character/found.pac"),
    ]
    evidence = {
        "missing": DonorEvidence(verified=False),
        "found": DonorEvidence(verified=True, sidecar_paths=("character/found.pac_xml",)),
    }

    ranked = rank_donors("Boots.nif", catalog=catalog, evidence_by_id=evidence)

    assert [recommendation.entry.id for recommendation in ranked] == ["found"]


def test_bounds_compatibility_compares_shape_independent_of_scale_and_axis_order():
    source = MeshIR(positions=np.array([[0, 0, 0], [2, 4, 1]], dtype=np.float32))
    same_shape = MeshIR(positions=np.array([[0, 0, 0], [10, 5, 20]], dtype=np.float32))
    different_shape = MeshIR(positions=np.array([[0, 0, 0], [20, 1, 1]], dtype=np.float32))

    assert bounds_compatibility(source, same_shape) == pytest.approx(1.0)
    assert bounds_compatibility(source, different_shape) < 0.85


def test_recommendation_output_has_top_choice_alternates_and_no_false_conversion_claim():
    ranked = rank_donors("Hood_1.nif", catalog=_small_catalog())

    output = format_recommendations("Hood_1.nif", ranked)

    assert output.startswith("Recommended donor: Head A")
    assert "Alternates:" in output
    assert "Head B" in output
    assert "only a practical Blender/game starting target" in output
    assert "does not guarantee fit" in output
    assert "finished wearable/game-ready conversion" in output


def test_recommendation_json_schema_preserves_ranking_signals_and_boundary(tmp_path):
    evidence = {
        "head_a": DonorEvidence(
            verified=True,
            ingame_name="Earth Honor Hood",
            sidecar_paths=("character/head_a.pac_xml", "character/head_a_n.dds"),
            bounds_compatibility=0.85,
        )
    }
    ranked = rank_donors("Hood_1.nif", catalog=_small_catalog(), evidence_by_id=evidence)

    output_path = write_recommendation_json(
        tmp_path / "donor_suggestion.json",
        "Hood_1.nif",
        ranked,
    )
    payload = recommendation_payload("Hood_1.nif", ranked)
    written = __import__("json").loads(output_path.read_text(encoding="utf-8"))

    assert written == payload
    assert written["schema_version"] == 1
    assert written["input_piece"] == "Hood_1.nif"
    assert written["inferred_slot"] == "head"
    assert written["recommended_donor_id"] == "head_a"
    assert written["recommended"]["rank"] == 1
    assert written["recommended"]["ingame_display_name"] == "Earth Honor Hood"
    assert written["recommended"]["signals"]["live_source_verified"] is True
    assert written["recommended"]["signals"]["material_sidecar_found"] is True
    assert written["alternates"][0]["rank"] == 2
    assert "does not guarantee fit" in written["artist_validation_boundary"]
    assert "game-ready conversion" in written["artist_validation_boundary"]


def test_gather_live_evidence_reuses_verification_sidecars_names_and_exported_bounds(
    tmp_path, monkeypatch
):
    from sky2cd import donor_recommendation

    source_path = tmp_path / "Boots.obj"
    source_path.write_text("v 0 0 0\nv 2 4 1\nf 1 1 2\n", encoding="utf-8")
    entry = DonorEntry(
        id="feet_live",
        display_name="Cryptic Feet",
        slot="feet",
        entry_path="character/feet_live.pac",
    )

    monkeypatch.setattr(
        donor_recommendation,
        "verify_against_install",
        lambda vfs, entries: [DonorVerificationResult(entry, True, "0009")],
    )
    monkeypatch.setattr(
        donor_recommendation.cfb,
        "build_item_name_resolver",
        lambda cf, vfs: type("_Resolver", (), {"resolve": lambda self, path: "Named Boots"})(),
    )
    monkeypatch.setattr(
        donor_recommendation.cfb,
        "find_sidecar_files",
        lambda vfs, path, group: [
            type("_Sidecar", (), {"path": "character/feet_live.pac_xml"})(),
            type("_Sidecar", (), {"path": "character/feet_live_n.dds"})(),
        ],
    )
    monkeypatch.setattr(
        donor_recommendation.cfb,
        "read_donor_pac_bytes",
        lambda vfs, path, group: b"PAC",
    )

    def export_obj(cf, pac_bytes, entry_path, out_dir):
        output = Path(out_dir) / "feet_live.obj"
        output.write_text("v 0 0 0\nv 10 5 20\nf 1 1 2\n", encoding="utf-8")
        return output

    monkeypatch.setattr(donor_recommendation.cfb, "export_donor_obj", export_obj)

    [evidence] = gather_live_evidence(
        source_path, [entry], cf=object(), vfs=object()
    ).values()

    assert evidence.verified is True
    assert evidence.ingame_name == "Named Boots"
    assert evidence.has_material_sidecar
    assert evidence.texture_count == 1
    assert evidence.bounds_compatibility == pytest.approx(1.0)
