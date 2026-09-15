"""Integration test for `sky2cd.auto_replace` (Skyrim outfit -> real DMM mod),
using fakes for the CrimsonForge bridge calls so this test has no dependency
on an actual CrimsonForge/game install being present.
"""

from __future__ import annotations

import json
import zipfile
import warnings
from pathlib import Path

import numpy as np
import pytest

from sky2cd import auto_replace
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


def test_auto_replace_from_skyrim_end_to_end(tmp_path, monkeypatch, fitting_config):
    mesh = MeshIR(
        positions=np.array([[0.0, 0.0, 100.0], [1.0, 0.0, 100.0], [0.0, 1.0, 100.0]], dtype=np.float32),
        normals=np.array([[0.0, 1.0, 0.0]] * 3, dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        name="auto_replace_test_outfit",
    )
    mesh_path = save_meshir(mesh, tmp_path / "outfit.meshir.json")

    donor = DonorEntry(
        id="fake_donor",
        display_name="Fake Donor Item",
        slot="lowerbody",
        entry_path="character/fake_donor.pac",
        package_group="0009",
    )

    monkeypatch.setattr(auto_replace.cfb, "load_crimsonforge_modules", lambda home: object())
    monkeypatch.setattr(auto_replace.cfb, "open_vfs", lambda cf, packages_path: object())
    monkeypatch.setattr(
        auto_replace.cfb, "read_donor_pac_bytes", lambda vfs, entry_path, group: b"ORIGINAL_DONOR_PAC_BYTES"
    )
    monkeypatch.setattr(auto_replace.cfb, "export_donor_obj", _write_fake_donor_obj)
    monkeypatch.setattr(auto_replace.cfb, "rebuild_pac", lambda cf, merged_obj_path, original: b"REBUILT_REAL_PAC_BYTES")
    monkeypatch.setattr(
        auto_replace.cfb,
        "read_sidecar_files",
        lambda vfs, entry_path, group: {
            "character/fake_donor.pac_xml": b"FAKE_XML",
            "character/fake_donor_n.dds": b"FAKE_NORMAL_TEXTURE",
        },
    )

    result = auto_replace.auto_replace_from_skyrim(
        mesh_path,
        fitting_config,
        donor,
        packages_path=tmp_path / "fake_packages",
        crimsonforge_home=tmp_path / "fake_crimsonforge",
        out_dir=tmp_path / "out",
        title="Auto Replace Test Mod",
    )

    assert result.conversion_report_path.is_file()
    assert result.merged_obj_path.is_file()
    assert result.rebuilt_pac_path.read_bytes() == b"REBUILT_REAL_PAC_BYTES"
    assert result.rebuilt_pac_path.name == "fake_donor.pac"
    assert result.decimated is False
    assert result.outfit_vertex_count_before == result.outfit_vertex_count_after == 3
    assert result.sidecar_file_paths == ["character/fake_donor.pac_xml", "character/fake_donor_n.dds"]

    installed_pac = result.dmm_package.mod_dir / "files" / "character" / "fake_donor.pac"
    assert installed_pac.is_file()
    assert installed_pac.read_bytes() == b"REBUILT_REAL_PAC_BYTES"
    installed_xml = result.dmm_package.mod_dir / "files" / "character" / "fake_donor.pac_xml"
    assert installed_xml.read_bytes() == b"FAKE_XML"
    installed_texture = result.dmm_package.mod_dir / "files" / "character" / "fake_donor_n.dds"
    assert installed_texture.read_bytes() == b"FAKE_NORMAL_TEXTURE"
    from sky2cd.importers.obj_importer import read_obj
    converted = read_obj(result.selected_mesh_piece)
    merged = read_obj(result.merged_obj_path)
    np.testing.assert_allclose(merged.positions[-3:], converted.positions, atol=1e-6)
    np.testing.assert_allclose(merged.normals[-3:], converted.normals, atol=1e-6)
    np.testing.assert_allclose(merged.uvs[-3:], converted.uvs, atol=1e-6)


def _write_fake_donor_obj_many_verts(cf, pac_bytes, entry_path, out_dir):
    # A donor mesh with ~65,025 real, face-referenced vertices, leaving very
    # little budget for the outfit -- forces auto_replace_from_skyrim's
    # automatic decimation path. (`read_obj` only keeps vertices actually
    # referenced by a face, so this must be a real triangulated mesh, not
    # just a long list of unused `v` lines.)
    from sky2cd.exporters.obj_exporter import write_obj

    name = Path(entry_path).stem
    donor_mesh = _grid_mesh(255, name)  # 255*255 = 65025 vertices
    return write_obj(donor_mesh, Path(out_dir) / f"{name}.obj")


def _grid_mesh(n: int, name: str) -> MeshIR:
    # An (n x n) grid of quads (2 triangles each), well above the tiny vertex
    # budget left once a 65,000-vertex donor is accounted for.
    xs, ys = np.meshgrid(np.arange(n, dtype=np.float32), np.arange(n, dtype=np.float32))
    positions = np.stack([xs.ravel(), ys.ravel(), np.full(n * n, 200.0, dtype=np.float32)], axis=1)
    triangles = []
    for row in range(n - 1):
        for col in range(n - 1):
            a = row * n + col
            b = row * n + col + 1
            c = (row + 1) * n + col
            d = (row + 1) * n + col + 1
            triangles.append([a, b, d])
            triangles.append([a, d, c])
    return MeshIR(
        positions=positions,
        triangles=np.array(triangles, dtype=np.uint32),
        name=name,
    )


def test_auto_replace_decimates_outfit_to_fit_real_pac_vertex_limit(tmp_path, monkeypatch, fitting_config):
    mesh = _grid_mesh(60, "large_outfit")  # 3600 vertices, well over the ~35-vertex budget below
    mesh_path = save_meshir(mesh, tmp_path / "large_outfit.meshir.json")

    donor = DonorEntry(
        id="fake_big_donor",
        display_name="Fake Big Donor Item",
        slot="lowerbody",
        entry_path="character/fake_big_donor.pac",
        package_group="0009",
    )

    monkeypatch.setattr(auto_replace.cfb, "load_crimsonforge_modules", lambda home: object())
    monkeypatch.setattr(auto_replace.cfb, "open_vfs", lambda cf, packages_path: object())
    monkeypatch.setattr(
        auto_replace.cfb, "read_donor_pac_bytes", lambda vfs, entry_path, group: b"ORIGINAL_DONOR_PAC_BYTES"
    )
    monkeypatch.setattr(auto_replace.cfb, "export_donor_obj", _write_fake_donor_obj_many_verts)
    monkeypatch.setattr(auto_replace.cfb, "rebuild_pac", lambda cf, merged_obj_path, original: b"REBUILT_REAL_PAC_BYTES")
    monkeypatch.setattr(auto_replace.cfb, "read_sidecar_files", lambda vfs, entry_path, group: {})

    result = auto_replace.auto_replace_from_skyrim(
        mesh_path,
        fitting_config,
        donor,
        packages_path=tmp_path / "fake_packages",
        crimsonforge_home=tmp_path / "fake_crimsonforge",
        out_dir=tmp_path / "out",
        title="Auto Replace Decimation Test Mod",
    )

    assert result.decimated is True
    assert result.outfit_vertex_count_before == 3600
    # Budget = 65535 (limit) - 65025 (donor, 255*255 grid) - 500 (safety margin) = 10.
    assert result.outfit_vertex_count_after <= 10


def _write_multi_piece_archive(tmp_path: Path) -> Path:
    # Real, confirmed gap this covers: a Skyrim outfit archive can contain
    # several separate armor pieces (e.g. the real Sherwood Huntress mod
    # tested live has Boots/Dress/Gloves/Hood as four distinct .nif meshes,
    # not one) -- auto_replace_from_skyrim previously always silently used
    # only the first piece found and discarded the rest with no warning.
    pack_dir = tmp_path / "multi_piece_pack"
    for piece_name in ("boots", "gloves", "hood"):
        mesh = MeshIR(
            positions=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
            normals=np.array([[0.0, 0.0, 1.0]] * 3, dtype=np.float32),
            uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
            triangles=np.array([[0, 1, 2]], dtype=np.uint32),
            name=piece_name,
        )
        save_meshir(mesh, pack_dir / f"{piece_name}.meshir.json")

    zip_path = tmp_path / "multi_piece_outfit.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for piece_name in ("boots", "gloves", "hood"):
            zf.write(pack_dir / f"{piece_name}.meshir.json", arcname=f"{piece_name}.meshir.json")
            zf.write(pack_dir / f"{piece_name}.meshir.npz", arcname=f"{piece_name}.meshir.npz")
    return zip_path


def _patch_auto_replace_fakes(monkeypatch):
    monkeypatch.setattr(auto_replace.cfb, "load_crimsonforge_modules", lambda home: object())
    monkeypatch.setattr(auto_replace.cfb, "open_vfs", lambda cf, packages_path: object())
    monkeypatch.setattr(
        auto_replace.cfb, "read_donor_pac_bytes", lambda vfs, entry_path, group: b"ORIGINAL_DONOR_PAC_BYTES"
    )
    monkeypatch.setattr(auto_replace.cfb, "export_donor_obj", _write_fake_donor_obj)
    monkeypatch.setattr(auto_replace.cfb, "rebuild_pac", lambda cf, merged_obj_path, original: b"REBUILT_REAL_PAC_BYTES")
    monkeypatch.setattr(auto_replace.cfb, "read_sidecar_files", lambda vfs, entry_path, group: {})


def test_auto_replace_defaults_to_first_piece_and_warns_about_the_rest(tmp_path, monkeypatch, fitting_config):
    zip_path = _write_multi_piece_archive(tmp_path)
    donor = DonorEntry(
        id="fake_donor",
        display_name="Fake Donor Item",
        slot="lowerbody",
        entry_path="character/fake_donor.pac",
        package_group="0009",
    )
    _patch_auto_replace_fakes(monkeypatch)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = auto_replace.auto_replace_from_skyrim(
            zip_path,
            fitting_config,
            donor,
            packages_path=tmp_path / "fake_packages",
            crimsonforge_home=tmp_path / "fake_crimsonforge",
            out_dir=tmp_path / "out",
            title="Multi Piece Default Test Mod",
        )

    assert "boots" in Path(result.selected_mesh_piece).name
    assert result.unselected_mesh_pieces == ["gloves.meshir.json", "hood.meshir.json"]
    assert any("gloves.meshir.json" in str(w.message) and "hood.meshir.json" in str(w.message) for w in caught)


def test_auto_replace_mesh_selector_picks_the_matching_piece(tmp_path, monkeypatch, fitting_config):
    zip_path = _write_multi_piece_archive(tmp_path)
    donor = DonorEntry(
        id="fake_donor",
        display_name="Fake Donor Item",
        slot="hands",
        entry_path="character/fake_donor.pac",
        package_group="0009",
    )
    _patch_auto_replace_fakes(monkeypatch)

    result = auto_replace.auto_replace_from_skyrim(
        zip_path,
        fitting_config,
        donor,
        packages_path=tmp_path / "fake_packages",
        crimsonforge_home=tmp_path / "fake_crimsonforge",
        out_dir=tmp_path / "out",
        title="Multi Piece Selector Test Mod",
        mesh_selector="gloves",
    )

    assert "gloves" in Path(result.selected_mesh_piece).name
    assert result.unselected_mesh_pieces == ["boots.meshir.json", "hood.meshir.json"]


def test_auto_replace_batch_covers_every_piece_in_one_dmm_package(tmp_path, monkeypatch, fitting_config):
    # Real underlying motivation: a full Skyrim outfit like Sherwood Huntress
    # has 4 separate pieces (Boots/Dress/Gloves/Hood) that each need their own
    # donor -- this proves a single call can cover all of them and produce
    # ONE combined, droppable DMM package instead of 4 separate ones.
    zip_path = _write_multi_piece_archive(tmp_path)
    boots_donor = DonorEntry(
        id="fake_feet_donor", display_name="Fake Feet", slot="feet",
        entry_path="character/fake_feet.pac", package_group="0009",
    )
    gloves_donor = DonorEntry(
        id="fake_hands_donor", display_name="Fake Hands", slot="hands",
        entry_path="character/fake_hands.pac", package_group="0009",
    )
    _patch_auto_replace_fakes(monkeypatch)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = auto_replace.auto_replace_batch_from_skyrim(
            zip_path,
            fitting_config,
            [
                auto_replace.PieceReplacement(mesh_selector="boots", donor=boots_donor),
                auto_replace.PieceReplacement(mesh_selector="gloves", donor=gloves_donor),
            ],
            packages_path=tmp_path / "fake_packages",
            crimsonforge_home=tmp_path / "fake_crimsonforge",
            out_dir=tmp_path / "out_batch",
            title="Multi Piece Batch Test Mod",
        )

    assert len(result.pieces) == 2
    assert {p.donor_entry_path for p in result.pieces} == {"character/fake_feet.pac", "character/fake_hands.pac"}
    assert result.unmatched_mesh_pieces == ["hood.meshir.json"]
    assert any("hood.meshir.json" in str(w.message) for w in caught)
    # Both .pac files must land in the SAME package folder (one droppable mod).
    assert (result.dmm_package.mod_dir / "files" / "character" / "fake_feet.pac").is_file()
    assert (result.dmm_package.mod_dir / "files" / "character" / "fake_hands.pac").is_file()


def test_auto_replace_batch_parallel_dispatch_preserves_piece_order(tmp_path, monkeypatch, fitting_config):
    # Real perf feature: `max_workers != 1` dispatches pieces concurrently via
    # ProcessPoolExecutor instead of one at a time. Genuine OS-process
    # spawning can't see this test's monkeypatched cfb fakes (each spawned
    # process re-imports sky2cd.crimsonforge_bridge fresh from disk instead
    # of inheriting the patched in-memory module), so this test substitutes
    # ThreadPoolExecutor for ProcessPoolExecutor -- same dispatch/ordering
    # code path (`executor.map(_process_one_piece_worker, ...)`), same
    # in-process memory space the monkeypatches actually apply to. This
    # verifies sky2cd's own order-preserving assembly logic is correct;
    # real cross-process execution is verified separately via a live run
    # against the actual game + CrimsonForge install.
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(auto_replace, "ProcessPoolExecutor", ThreadPoolExecutor)

    zip_path = _write_multi_piece_archive(tmp_path)
    boots_donor = DonorEntry(
        id="fake_feet_donor", display_name="Fake Feet", slot="feet",
        entry_path="character/fake_feet.pac", package_group="0009",
    )
    gloves_donor = DonorEntry(
        id="fake_hands_donor", display_name="Fake Hands", slot="hands",
        entry_path="character/fake_hands.pac", package_group="0009",
    )
    hood_donor = DonorEntry(
        id="fake_head_donor", display_name="Fake Head", slot="head",
        entry_path="character/fake_head.pac", package_group="0009",
    )
    _patch_auto_replace_fakes(monkeypatch)

    result = auto_replace.auto_replace_batch_from_skyrim(
        zip_path,
        fitting_config,
        [
            auto_replace.PieceReplacement(mesh_selector="boots", donor=boots_donor),
            auto_replace.PieceReplacement(mesh_selector="gloves", donor=gloves_donor),
            auto_replace.PieceReplacement(mesh_selector="hood", donor=hood_donor),
        ],
        packages_path=tmp_path / "fake_packages",
        crimsonforge_home=tmp_path / "fake_crimsonforge",
        out_dir=tmp_path / "out_parallel",
        title="Parallel Batch Test Mod",
        max_workers=2,
    )

    # Piece results must come back in the SAME order `pieces` was given in,
    # not whatever order the (thread/process) pool happened to finish them.
    assert [p.mesh_selector for p in result.pieces] == ["boots", "gloves", "hood"]
    assert [p.donor_entry_path for p in result.pieces] == [
        "character/fake_feet.pac",
        "character/fake_hands.pac",
        "character/fake_head.pac",
    ]
    assert result.unmatched_mesh_pieces == []
    for name in ("fake_feet.pac", "fake_hands.pac", "fake_head.pac"):
        assert (result.dmm_package.mod_dir / "files" / "character" / name).is_file()


def test_auto_replace_batch_auto_selects_donors_when_pieces_is_none(tmp_path, monkeypatch, fitting_config):
    # Real motivation: previously EVERY piece needed a manually-typed
    # --piece "mesh_selector=donor_id", even for an unambiguous outfit
    # (boots/gloves/hood, one obvious donor each) -- defeating the point of
    # an "automated" tool. pieces=None should resolve all three without any
    # manual mapping.
    zip_path = _write_multi_piece_archive(tmp_path)
    boots_donor = DonorEntry(
        id="fake_feet_donor", display_name="Fake Feet", slot="feet",
        entry_path="character/fake_feet.pac", package_group="0009",
    )
    gloves_donor = DonorEntry(
        id="fake_hands_donor", display_name="Fake Hands", slot="hands",
        entry_path="character/fake_hands.pac", package_group="0009",
    )
    hood_donor = DonorEntry(
        id="fake_head_donor", display_name="Fake Head", slot="head",
        entry_path="character/fake_head.pac", package_group="0009",
    )
    donor_by_relative_path = {
        "boots.meshir.json": boots_donor,
        "gloves.meshir.json": gloves_donor,
        "hood.meshir.json": hood_donor,
    }
    from sky2cd import donor_auto_select

    monkeypatch.setattr(
        auto_replace,
        "auto_select_donors",
        lambda relative_paths, catalog=None: [
            donor_auto_select.PieceDonorGuess(
                relative_path=rp, guessed_slot="fake_slot", candidates=[donor_by_relative_path[rp]]
            )
            for rp in relative_paths
        ],
    )
    _patch_auto_replace_fakes(monkeypatch)

    result = auto_replace.auto_replace_batch_from_skyrim(
        zip_path,
        fitting_config,
        None,
        packages_path=tmp_path / "fake_packages",
        crimsonforge_home=tmp_path / "fake_crimsonforge",
        out_dir=tmp_path / "out_auto",
        title="Auto Select Test Mod",
    )

    assert {p.donor_entry_path for p in result.pieces} == {
        "character/fake_feet.pac",
        "character/fake_hands.pac",
        "character/fake_head.pac",
    }
    assert result.unmatched_mesh_pieces == []
    assert result.ambiguous_mesh_pieces == []


def test_auto_replace_batch_auto_select_handles_pieces_nested_in_archive_subfolders(tmp_path, monkeypatch, fitting_config):
    # Real, live-confirmed bug: real Skyrim mod archives nest their meshes
    # under subfolders (e.g. "[My Mod]\\meshes\\Armor\\[My Mod]\\Boots_1.nif"),
    # so auto-selection's mesh_selector (the piece's full relative path, used
    # so `_match_piece_index` finds that exact piece) previously flowed
    # straight into the output filename tag -- producing a nested, "No such
    # file or directory" write failure the moment CrimsonForge tried to
    # write the rebuilt .pac. Confirmed live against the real Sherwood
    # Huntress archive + real game before this was fixed.
    import zipfile
    from sky2cd.meshir import MeshIR, save_meshir

    pack_dir = tmp_path / "nested_pack"
    subfolder = "[My Mod]/meshes/Armor/[My Mod]"
    for piece_name in ("boots", "gloves"):
        mesh = MeshIR(
            positions=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
            normals=np.array([[0.0, 0.0, 1.0]] * 3, dtype=np.float32),
            uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
            triangles=np.array([[0, 1, 2]], dtype=np.uint32),
            name=piece_name,
        )
        save_meshir(mesh, pack_dir / f"{piece_name}.meshir.json")

    zip_path = tmp_path / "nested_outfit.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for piece_name in ("boots", "gloves"):
            zf.write(pack_dir / f"{piece_name}.meshir.json", arcname=f"{subfolder}/{piece_name}.meshir.json")
            zf.write(pack_dir / f"{piece_name}.meshir.npz", arcname=f"{subfolder}/{piece_name}.meshir.npz")

    boots_donor = DonorEntry(
        id="fake_feet_donor", display_name="Fake Feet", slot="feet",
        entry_path="character/fake_feet.pac", package_group="0009",
    )
    gloves_donor = DonorEntry(
        id="fake_hands_donor", display_name="Fake Hands", slot="hands",
        entry_path="character/fake_hands.pac", package_group="0009",
    )
    from sky2cd import donor_auto_select

    monkeypatch.setattr(
        auto_replace,
        "auto_select_donors",
        lambda relative_paths, catalog=None: [
            donor_auto_select.PieceDonorGuess(
                relative_path=rp,
                guessed_slot="fake_slot",
                candidates=[boots_donor if "boots" in rp.lower() else gloves_donor],
            )
            for rp in relative_paths
        ],
    )
    _patch_auto_replace_fakes(monkeypatch)

    result = auto_replace.auto_replace_batch_from_skyrim(
        zip_path,
        fitting_config,
        None,
        packages_path=tmp_path / "fake_packages",
        crimsonforge_home=tmp_path / "fake_crimsonforge",
        out_dir=tmp_path / "out_auto_nested",
        title="Auto Select Nested Test Mod",
    )

    assert len(result.pieces) == 2
    for piece in result.pieces:
        # Must be a flat filename directly inside out_dir, never a path
        # containing the archive's nested subfolder separators/brackets.
        assert piece.rebuilt_pac_path.parent == (tmp_path / "out_auto_nested")
        assert piece.rebuilt_pac_path.is_file()


def test_auto_replace_batch_auto_select_reports_ambiguous_pieces_without_converting_them(tmp_path, monkeypatch, fitting_config):
    # Real motivation: if the catalog ever has MORE THAN ONE donor for the
    # same guessed slot, auto-selection must not silently guess which one to
    # use -- it should report the piece as ambiguous (with every candidate
    # id) and leave it unconverted, same as an unmatched piece, so the user
    # can cover it with an explicit --piece instead.
    zip_path = _write_multi_piece_archive(tmp_path)
    boots_donor = DonorEntry(
        id="fake_feet_donor", display_name="Fake Feet", slot="feet",
        entry_path="character/fake_feet.pac", package_group="0009",
    )
    hood_candidate_a = DonorEntry(
        id="fake_head_a", display_name="Fake Head A", slot="head", entry_path="character/fake_head_a.pac",
    )
    hood_candidate_b = DonorEntry(
        id="fake_head_b", display_name="Fake Head B", slot="head", entry_path="character/fake_head_b.pac",
    )
    from sky2cd import donor_auto_select

    def fake_auto_select_donors(relative_paths, catalog=None):
        guesses = []
        for rp in relative_paths:
            if rp == "boots.meshir.json":
                guesses.append(donor_auto_select.PieceDonorGuess(rp, "feet", [boots_donor]))
            elif rp == "hood.meshir.json":
                guesses.append(donor_auto_select.PieceDonorGuess(rp, "head", [hood_candidate_a, hood_candidate_b]))
            else:
                guesses.append(donor_auto_select.PieceDonorGuess(rp, None, []))
        return guesses

    monkeypatch.setattr(auto_replace, "auto_select_donors", fake_auto_select_donors)
    _patch_auto_replace_fakes(monkeypatch)

    result = auto_replace.auto_replace_batch_from_skyrim(
        zip_path,
        fitting_config,
        None,
        packages_path=tmp_path / "fake_packages",
        crimsonforge_home=tmp_path / "fake_crimsonforge",
        out_dir=tmp_path / "out_auto_ambiguous",
        title="Auto Select Ambiguous Test Mod",
    )

    assert [p.donor_entry_path for p in result.pieces] == ["character/fake_feet.pac"]
    assert "hood.meshir.json" in result.unmatched_mesh_pieces
    assert "gloves.meshir.json" in result.unmatched_mesh_pieces
    assert len(result.ambiguous_mesh_pieces) == 1
    assert result.ambiguous_mesh_pieces[0]["relative_path"] == "hood.meshir.json"
    assert set(result.ambiguous_mesh_pieces[0]["candidate_donor_ids"]) == {"fake_head_a", "fake_head_b"}


def test_auto_replace_batch_auto_select_raises_when_nothing_resolves(tmp_path, monkeypatch, fitting_config):
    zip_path = _write_multi_piece_archive(tmp_path)
    from sky2cd import donor_auto_select

    monkeypatch.setattr(
        auto_replace,
        "auto_select_donors",
        lambda relative_paths, catalog=None: [
            donor_auto_select.PieceDonorGuess(rp, None, []) for rp in relative_paths
        ],
    )
    _patch_auto_replace_fakes(monkeypatch)

    import pytest

    with pytest.raises(ValueError, match="could not confidently resolve"):
        auto_replace.auto_replace_batch_from_skyrim(
            zip_path,
            fitting_config,
            None,
            packages_path=tmp_path / "fake_packages",
            crimsonforge_home=tmp_path / "fake_crimsonforge",
            out_dir=tmp_path / "out_auto_none",
            title="Auto Select Nothing Resolved Test Mod",
        )


def test_auto_replace_batch_rejects_empty_pieces_list(tmp_path, monkeypatch):
    zip_path = _write_multi_piece_archive(tmp_path)
    _patch_auto_replace_fakes(monkeypatch)

    import pytest

    with pytest.raises(ValueError, match="pieces must not be empty"):
        auto_replace.auto_replace_batch_from_skyrim(
            zip_path,
            "fem_kliff",
            [],
            packages_path=tmp_path / "fake_packages",
            crimsonforge_home=tmp_path / "fake_crimsonforge",
            out_dir=tmp_path / "out_batch_empty",
            title="Empty Batch Test Mod",
        )


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("preset", ["fem_kliff", "cd_vanilla_female"])
def test_preview_packaging_blocked_before_cf_or_game_access(tmp_path, monkeypatch, batch, preset):
    def forbidden(*args, **kwargs):
        pytest.fail("Preview must not convert or access CrimsonForge/game archives for packaging")
    monkeypatch.setattr(auto_replace, "convert", forbidden)
    monkeypatch.setattr(auto_replace.cfb, "load_crimsonforge_modules", forbidden)
    monkeypatch.setattr(auto_replace.cfb, "open_vfs", forbidden)
    call = auto_replace.auto_replace_batch_from_skyrim if batch else auto_replace.auto_replace_from_skyrim
    with pytest.raises(ValueError, match="packaging is blocked"):
        call(tmp_path / "unused.nif", preset, None, tmp_path / "game", tmp_path / "cf",
             tmp_path / "out", title="Blocked")
    assert not list((tmp_path / "out").rglob("*.pac"))
