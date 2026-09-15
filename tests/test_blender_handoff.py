"""Tests for `sky2cd.blender_handoff`: the artist-handoff path that converts
a Skyrim outfit + exports its real donor item(s) into a self-contained
Blender import bundle, WITHOUT ever claiming a body fit or producing a DMM
package. Uses the same CrimsonForge-bridge fakes as `test_auto_replace.py`
so this has no dependency on a real CrimsonForge/game install.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sky2cd import blender_handoff
from sky2cd.auto_replace import PieceReplacement
from sky2cd.donor_catalog import DonorEntry
from sky2cd.meshir import MeshIR, save_meshir


def _write_fake_donor_obj(cf, pac_bytes, entry_path, out_dir):
    name = Path(entry_path).stem
    obj_path = Path(out_dir) / f"{name}.obj"
    obj_path.write_text(
        "v -1.0 0.0 0.0\nv 1.0 0.0 0.0\nv 0.0 1.0 0.0\nf 1 2 3\n",
        encoding="utf-8",
    )
    return obj_path


def _simple_mesh(name: str) -> MeshIR:
    return MeshIR(
        positions=np.array([[0.0, 0.0, 100.0], [1.0, 0.0, 100.0], [0.0, 1.0, 100.0]], dtype=np.float32),
        normals=np.array([[0.0, 1.0, 0.0]] * 3, dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        name=name,
    )


def test_build_blender_handoff_source_only_when_no_game_install_given(tmp_path, fitting_config):
    mesh_path = save_meshir(_simple_mesh("handoff_outfit"), tmp_path / "outfit.meshir.json")
    donor = DonorEntry(
        id="fake_donor",
        display_name="Fake Donor Item",
        slot="lowerbody",
        entry_path="character/fake_donor.pac",
        package_group="0009",
    )

    result = blender_handoff.build_blender_handoff(
        mesh_path,
        fitting_config,
        [PieceReplacement(mesh_selector="<single piece>", donor=donor)],
        packages_path=None,
        crimsonforge_home=None,
        out_dir=tmp_path / "out",
    )

    assert result.conversion_report_path.is_file()
    assert len(result.pieces) == 1
    piece = result.pieces[0]
    assert piece.source_obj_path.is_file()
    assert piece.donor is not None
    assert piece.donor.obj_path is None
    assert piece.donor.error is not None
    assert "no CrimsonForge/game install" in piece.donor.error
    assert any("source-only" in w for w in result.warnings)
    assert result.import_script_path.is_file()
    script_text = result.import_script_path.read_text(encoding="utf-8")
    assert "sky2cd_source_" in script_text
    assert "sky2cd_donor_" not in script_text  # no donor was exported, so no donor import line


def test_build_blender_handoff_with_donor_export(tmp_path, monkeypatch, fitting_config):
    mesh_path = save_meshir(_simple_mesh("handoff_outfit_full"), tmp_path / "outfit.meshir.json")
    donor = DonorEntry(
        id="fake_donor",
        display_name="Fake Donor Item",
        slot="lowerbody",
        entry_path="character/fake_donor.pac",
        package_group="0009",
    )

    monkeypatch.setattr(blender_handoff.cfb, "load_crimsonforge_modules", lambda home: object())
    monkeypatch.setattr(blender_handoff.cfb, "open_vfs", lambda cf, packages_path: object())
    monkeypatch.setattr(
        blender_handoff.cfb, "read_donor_pac_bytes", lambda vfs, entry_path, group: b"ORIGINAL_DONOR_PAC_BYTES"
    )
    monkeypatch.setattr(blender_handoff.cfb, "export_donor_obj", _write_fake_donor_obj)
    monkeypatch.setattr(
        blender_handoff.cfb,
        "read_sidecar_files",
        lambda vfs, entry_path, group: {
            "character/fake_donor.pac_xml": b"FAKE_XML",
            "character/fake_donor_n.dds": b"FAKE_NORMAL_TEXTURE",
        },
    )
    monkeypatch.setattr(
        blender_handoff.cfb, "build_item_name_resolver", lambda cf, vfs: _FakeResolver("Fake In-Game Name")
    )

    result = blender_handoff.build_blender_handoff(
        mesh_path,
        fitting_config,
        [PieceReplacement(mesh_selector="<single piece>", donor=donor)],
        packages_path=tmp_path / "fake_packages",
        crimsonforge_home=tmp_path / "fake_crimsonforge",
        out_dir=tmp_path / "out",
    )

    assert result.warnings == []
    piece = result.pieces[0]
    assert piece.donor.obj_path is not None and piece.donor.obj_path.is_file()
    assert piece.donor.error is None
    assert piece.donor.ingame_display_name == "Fake In-Game Name"
    assert len(piece.donor.sidecar_paths) == 2
    for sidecar_path in piece.donor.sidecar_paths:
        assert sidecar_path.is_file()

    metadata = _read_json(piece.metadata_path)
    assert metadata["status"].startswith("NOT FITTED")
    assert metadata["donor"]["ingame_display_name"] == "Fake In-Game Name"
    assert metadata["donor"]["entry_path"] == "character/fake_donor.pac"

    script_text = result.import_script_path.read_text(encoding="utf-8")
    assert "sky2cd_source_" in script_text
    assert "sky2cd_donor_" in script_text


def test_build_blender_handoff_multi_piece_reports_unmatched(tmp_path, monkeypatch, fitting_config):
    import zipfile

    pack_dir = tmp_path / "multi_piece_pack"
    for piece_name in ("boots", "gloves"):
        save_meshir(_simple_mesh(piece_name), pack_dir / f"{piece_name}.meshir.json")
    zip_path = tmp_path / "multi_piece_outfit.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for piece_name in ("boots", "gloves"):
            zf.write(pack_dir / f"{piece_name}.meshir.json", arcname=f"{piece_name}.meshir.json")
            zf.write(pack_dir / f"{piece_name}.meshir.npz", arcname=f"{piece_name}.meshir.npz")

    monkeypatch.setattr(blender_handoff.cfb, "load_crimsonforge_modules", lambda home: object())
    monkeypatch.setattr(blender_handoff.cfb, "open_vfs", lambda cf, packages_path: object())
    monkeypatch.setattr(blender_handoff.cfb, "read_donor_pac_bytes", lambda vfs, entry_path, group: b"ORIG")
    monkeypatch.setattr(blender_handoff.cfb, "export_donor_obj", _write_fake_donor_obj)
    monkeypatch.setattr(blender_handoff.cfb, "read_sidecar_files", lambda vfs, entry_path, group: {})
    monkeypatch.setattr(blender_handoff.cfb, "build_item_name_resolver", lambda cf, vfs: _FakeResolver(None))

    donor = DonorEntry(id="boots_donor", display_name="Boots Donor", slot="feet", entry_path="character/boots_donor.pac")
    result = blender_handoff.build_blender_handoff(
        zip_path,
        fitting_config,
        [PieceReplacement(mesh_selector="boots", donor=donor)],
        packages_path=tmp_path / "packages",
        crimsonforge_home=tmp_path / "crimsonforge",
        out_dir=tmp_path / "out",
    )

    assert len(result.pieces) == 1
    assert result.unmatched_mesh_pieces == ["gloves.meshir.json"]
    suggestion_path = result.pieces[0].donor_suggestion_path
    assert suggestion_path is not None and suggestion_path.is_file()
    suggestion = _read_json(suggestion_path)
    assert suggestion["input_piece"] == "boots.meshir.json"
    assert suggestion["inferred_slot"] == "feet"
    assert suggestion["recommended"]["rank"] == 1
    assert suggestion["recommended"]["signals"]["live_source_verified"] is True
    assert "does not guarantee fit" in suggestion["artist_validation_boundary"]


def test_build_blender_handoff_auto_selects_donors_when_pieces_is_none(tmp_path, monkeypatch, fitting_config):
    import zipfile

    pack_dir = tmp_path / "auto_pack"
    for piece_name in ("hood", "gloves"):
        save_meshir(_simple_mesh(piece_name), pack_dir / f"{piece_name}.meshir.json")
    zip_path = tmp_path / "auto_outfit.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for piece_name in ("hood", "gloves"):
            zf.write(pack_dir / f"{piece_name}.meshir.json", arcname=f"{piece_name}.meshir.json")
            zf.write(pack_dir / f"{piece_name}.meshir.npz", arcname=f"{piece_name}.meshir.npz")

    monkeypatch.setattr(blender_handoff.cfb, "load_crimsonforge_modules", lambda home: object())
    monkeypatch.setattr(blender_handoff.cfb, "open_vfs", lambda cf, packages_path: object())
    monkeypatch.setattr(blender_handoff.cfb, "read_donor_pac_bytes", lambda vfs, entry_path, group: b"ORIG")
    monkeypatch.setattr(blender_handoff.cfb, "export_donor_obj", _write_fake_donor_obj)
    monkeypatch.setattr(blender_handoff.cfb, "read_sidecar_files", lambda vfs, entry_path, group: {})
    monkeypatch.setattr(blender_handoff.cfb, "build_item_name_resolver", lambda cf, vfs: _FakeResolver(None))

    result = blender_handoff.build_blender_handoff(
        zip_path,
        fitting_config,
        None,
        packages_path=tmp_path / "packages",
        crimsonforge_home=tmp_path / "crimsonforge",
        out_dir=tmp_path / "out",
    )

    selectors = {piece.mesh_selector for piece in result.pieces}
    assert "hood.meshir.json" in selectors
    assert "gloves.meshir.json" in selectors
    assert result.unmatched_mesh_pieces == []


def test_build_blender_handoff_raises_when_auto_select_resolves_nothing(tmp_path, fitting_config):
    mesh_path = save_meshir(_simple_mesh("unrecognized_piece_name_xyz"), tmp_path / "outfit.meshir.json")

    with pytest.raises(ValueError, match="could not confidently resolve"):
        blender_handoff.build_blender_handoff(
            mesh_path,
            fitting_config,
            None,
            packages_path=None,
            crimsonforge_home=None,
            out_dir=tmp_path / "out",
        )


class _FakeResolver:
    def __init__(self, name):
        self._name = name

    def resolve(self, entry_path):
        return self._name


def _read_json(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))
