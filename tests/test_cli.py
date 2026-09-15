import pytest

from sky2cd.cli import WELCOME, build_parser, main


def test_main_with_no_args_prints_welcome_and_usage_without_pausing(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "No command was given" in captured.out
    assert "usage: sky2cd" in captured.out


def test_cli_messaging_centers_blender_preview_and_marks_advanced_utilities_optional():
    parser = build_parser()
    help_text = parser.format_help()

    assert "Blender workflow" in WELCOME
    assert "preview/mockup" in WELCOME
    assert "not a fitted, rigged, tested, or game-ready outfit" in WELCOME
    assert "optional advanced utilities" in WELCOME
    assert "Recommended: create a Blender import bundle" in help_text
    assert "preview/mockup" in help_text
    assert "Advanced experimental" in help_text
    assert "not an automatic wearable" in help_text


def test_cli_convert_with_default_preset(tmp_path, monkeypatch):
    from sky2cd.meshir import MeshIR, save_meshir
    import numpy as np

    mesh = MeshIR(
        positions=np.array([[0.0, 0.0, 100.0], [1.0, 0.0, 100.0], [0.0, 1.0, 100.0]], dtype=np.float32),
        normals=np.array([[0.0, 1.0, 0.0]] * 3, dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        name="cli_test_outfit",
    )
    mesh_path = save_meshir(mesh, tmp_path / "outfit.meshir.json")
    out_dir = tmp_path / "cli_out"

    exit_code = main(["convert", str(mesh_path), "--out", str(out_dir)])
    assert exit_code == 0
    assert (out_dir / "outfit.pac").is_file()


def test_cli_convert_with_atlas_flag(tmp_path):
    from sky2cd.meshir import MeshIR, save_meshir
    import numpy as np

    mesh = MeshIR(
        positions=np.array([[0.0, 0.0, 100.0], [1.0, 0.0, 100.0], [0.0, 1.0, 100.0]], dtype=np.float32),
        normals=np.array([[0.0, 1.0, 0.0]] * 3, dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        materials=[{"name": "mat1"}],
        submesh_ids=np.array([0], dtype=np.int32),
        name="atlas_cli_outfit",
    )
    mesh_path = save_meshir(mesh, tmp_path / "atlas_outfit.meshir.json")
    out_dir = tmp_path / "atlas_cli_out"

    exit_code = main(["convert", str(mesh_path), "--out", str(out_dir), "--atlas"])
    assert exit_code == 0
    assert (out_dir / "atlas_outfit.pac").is_file()
    assert (out_dir / "atlas_outfit.obj").is_file()


def test_cli_presets_subcommand(capsys):
    exit_code = main(["presets"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "fem_kliff" in captured.out
    assert "cd_vanilla_female" in captured.out
    assert "Geometry preview only" in captured.out


@pytest.mark.parametrize("command", ["auto-replace", "auto-replace-all"])
def test_cli_default_preview_cannot_produce_dmm_package(tmp_path, monkeypatch, capsys, command):
    from sky2cd import auto_replace
    def forbidden(*args, **kwargs):
        pytest.fail("Blocked preview must not access CrimsonForge or game data")
    monkeypatch.setattr(auto_replace.cfb, "load_crimsonforge_modules", forbidden)
    monkeypatch.setattr(auto_replace.cfb, "open_vfs", forbidden)
    args = [command, "--input", str(tmp_path / "unused.nif"),
            "--packages-path", str(tmp_path / "game"), "--crimsonforge-home", str(tmp_path / "cf"),
            "--title", "Blocked", "--out", str(tmp_path / "out")]
    if command == "auto-replace":
        args += ["--donor-id", "demenissian_elite_leather_lb"]
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 1
    output = capsys.readouterr()
    assert "packaging is blocked" in output.out + output.err
    assert not list((tmp_path / "out").rglob("*.pac"))


def test_cli_build_preset_and_reuse_it(tmp_path, capsys):
    from sky2cd.meshir import MeshIR, save_meshir
    import numpy as np

    def body_mesh(positions, name):
        n = len(positions)
        return MeshIR(
            positions=positions.astype(np.float32),
            triangles=np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.uint32),
            bone_names=["Root"],
            name=name,
        )

    source = body_mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]), "cbbe_base")
    target = body_mesh(np.array([[0, 0, 0], [1.2, 0, 0], [0, 1.3, 0], [0, 0, 1]]), "cd_reshaped")
    source_path = save_meshir(source, tmp_path / "source_body.meshir.json")
    target_path = save_meshir(target, tmp_path / "target_body.meshir.json")

    preset_dir = tmp_path / "presets"
    exit_code = main([
        "build-preset",
        "--source-body", str(source_path),
        "--target-body", str(target_path),
        "--name", "my_cli_preset",
        "--out", str(preset_dir),
    ])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Wrote" in captured.out
    config_path = preset_dir / "my_cli_preset.json"
    assert config_path.is_file()

    outfit = MeshIR(
        positions=np.array([[0.1, 0.1, 0.0], [0.9, 0.1, 0.0], [0.1, 0.9, 0.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        name="cli_reuse_outfit",
    )
    outfit_path = save_meshir(outfit, tmp_path / "outfit.meshir.json")
    out_dir = tmp_path / "out_reuse"
    exit_code = main(["convert", str(outfit_path), "--body-config", str(config_path), "--out", str(out_dir)])
    assert exit_code == 0
    assert (out_dir / "outfit.pac").is_file()


def test_cli_merge_produces_merged_obj(tmp_path, capsys):
    from sky2cd.exporters.obj_exporter import write_obj
    from sky2cd.meshir import MeshIR
    import numpy as np

    donor = MeshIR(
        positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2], [1, 3, 2]], dtype=np.uint32),
        name="donor_item",
    )
    outfit = MeshIR(
        positions=np.array([[0.1, 0.1, 0], [0.9, 0.1, 0], [0.1, 0.9, 0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        name="my_outfit",
    )
    donor_obj = write_obj(donor, tmp_path / "donor.obj", axis_convert=False)
    outfit_obj = write_obj(outfit, tmp_path / "outfit.obj", axis_convert=False)
    merged_out = tmp_path / "merged.obj"

    exit_code = main([
        "merge",
        "--donor", str(donor_obj),
        "--outfit", str(outfit_obj),
        "--out", str(merged_out),
    ])
    assert exit_code == 0
    assert merged_out.is_file()
    captured = capsys.readouterr()
    assert "VERIFIED against the real game" in captured.out

    from sky2cd.importers.obj_importer import read_obj
    merged_mesh = read_obj(merged_out)
    assert merged_mesh.vertex_count == donor.vertex_count + outfit.vertex_count


def test_cli_package_dmm_writes_loose_mod(tmp_path, capsys):
    pac_path = tmp_path / "merged.pac"
    pac_path.write_bytes(b"FAKE_PAC")
    out_dir = tmp_path / "dmm_out"

    exit_code = main([
        "package-dmm",
        "--pac", str(pac_path),
        "--entry-path", "character/cd_phw_00_lb_00_0182.pac",
        "--package-group", "0009",
        "--title", "Test Replacer Mod",
        "--out", str(out_dir),
    ])
    assert exit_code == 0

    mod_dir = out_dir / "Test_Replacer_Mod"
    assert (mod_dir / "manifest.json").is_file()
    assert (mod_dir / "modinfo.json").is_file()
    assert (mod_dir / "files" / "character" / "cd_phw_00_lb_00_0182.pac").read_bytes() == b"FAKE_PAC"

    captured = capsys.readouterr()
    assert "Drop this folder into your DMM" in captured.out


def test_cli_donors_lists_builtin_catalog(capsys):
    exit_code = main(["donors"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "demenissian_elite_leather_lb" in captured.out
    assert "character/cd_phw_00_lb_00_0182.pac" in captured.out


def test_cli_donors_suggests_human_readable_ranked_starting_points(capsys):
    exit_code = main(["donors", "--suggest", "Boots_1.nif"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert output.startswith("Recommended donor: Damian's Elite Uniform Leather Boots")
    assert "Alternates:" in output
    assert "donor id:" in output
    assert "only a practical Blender/game starting target" in output
    assert "does not guarantee fit" in output
    assert "game-ready conversion" in output


def test_cli_donors_suggest_out_writes_json_next_to_files(tmp_path, capsys):
    output_path = tmp_path / "references" / "boots_donors.json"

    exit_code = main([
        "donors",
        "--suggest", "Boots_1.nif",
        "--suggest-out", str(output_path),
    ])

    assert exit_code == 0
    payload = __import__("json").loads(output_path.read_text(encoding="utf-8"))
    assert payload["input_piece"] == "Boots_1.nif"
    assert payload["inferred_slot"] == "feet"
    assert payload["recommended_donor_id"] == "damian_elite_leather_boots"
    assert payload["recommended"]["rank"] == 1
    assert payload["alternates"][0]["rank"] == 2
    assert "does not guarantee fit" in payload["artist_validation_boundary"]
    assert f"Wrote {output_path}" in capsys.readouterr().out


def test_cli_donors_suggest_out_requires_suggest(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["donors", "--suggest-out", str(tmp_path / "donors.json")])

    assert error.value.code == 1


def test_cli_donors_suggest_requires_both_live_paths(tmp_path):
    with pytest.raises(SystemExit) as error:
        main([
            "donors",
            "--suggest", "Boots_1.nif",
            "--packages-path", str(tmp_path / "packages"),
        ])

    assert error.value.code == 1


def test_cli_package_dmm_strict_writes_provenance_when_sidecar_present(tmp_path, capsys):
    pac_path = tmp_path / "merged.pac"
    pac_path.write_bytes(b"FAKE_PAC")
    sidecar_path = tmp_path / "merged.pac_xml"
    sidecar_path.write_bytes(b"<xml/>")
    out_dir = tmp_path / "dmm_out"

    exit_code = main([
        "package-dmm",
        "--pac", str(pac_path),
        "--entry-path", "character/cd_phw_00_lb_00_0182.pac",
        "--title", "Strict CLI Mod",
        "--strict",
        "--sidecar", f"character/cd_phw_00_lb_00_0182.pac_xml={sidecar_path}",
        "--out", str(out_dir),
    ])
    assert exit_code == 0

    mod_dir = out_dir / "Strict_CLI_Mod"
    assert (mod_dir / "provenance.json").is_file()
    captured = capsys.readouterr()
    assert "STRICT MODE" in captured.out


def test_cli_package_dmm_strict_rejects_missing_sidecar(tmp_path):
    pac_path = tmp_path / "merged.pac"
    pac_path.write_bytes(b"FAKE_PAC")
    out_dir = tmp_path / "dmm_out"

    with pytest.raises(SystemExit):
        main([
            "package-dmm",
            "--pac", str(pac_path),
            "--entry-path", "character/cd_phw_00_lb_00_0182.pac",
            "--title", "Strict Reject Mod",
            "--strict",
            "--out", str(out_dir),
        ])
    assert not out_dir.exists()


def test_cli_donors_verify_requires_paths():
    with pytest.raises(SystemExit):
        main(["donors", "--verify"])


def test_cli_auto_replace_runs_full_pipeline_with_fakes(tmp_path, monkeypatch, fitting_config):
    from sky2cd import auto_replace
    from sky2cd.meshir import MeshIR, save_meshir
    import numpy as np

    mesh = MeshIR(
        positions=np.array([[0.0, 0.0, 100.0], [1.0, 0.0, 100.0], [0.0, 1.0, 100.0]], dtype=np.float32),
        normals=np.array([[0.0, 1.0, 0.0]] * 3, dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        name="cli_auto_replace_outfit",
    )
    mesh_path = save_meshir(mesh, tmp_path / "outfit.meshir.json")

    def _fake_export_donor_obj(cf, pac_bytes, entry_path, out_dir):
        from pathlib import Path as _Path

        obj_path = _Path(out_dir) / f"{_Path(entry_path).stem}.obj"
        obj_path.write_text("v -1 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
        return obj_path

    monkeypatch.setattr(auto_replace.cfb, "load_crimsonforge_modules", lambda home: object())
    monkeypatch.setattr(auto_replace.cfb, "open_vfs", lambda cf, packages_path: object())
    monkeypatch.setattr(auto_replace.cfb, "read_donor_pac_bytes", lambda vfs, entry_path, group: b"ORIG")
    monkeypatch.setattr(auto_replace.cfb, "export_donor_obj", _fake_export_donor_obj)
    monkeypatch.setattr(auto_replace.cfb, "rebuild_pac", lambda cf, obj_path, original: b"REBUILT")
    monkeypatch.setattr(auto_replace.cfb, "read_sidecar_files", lambda vfs, entry_path, group: {})

    exit_code = main([
        "auto-replace",
        "--body-config", str(fitting_config),
        "--input", str(mesh_path),
        "--donor-id", "demenissian_elite_leather_lb",
        "--packages-path", str(tmp_path / "packages"),
        "--crimsonforge-home", str(tmp_path / "crimsonforge"),
        "--title", "CLI Auto Replace Test",
        "--out", str(tmp_path / "out"),
    ])
    assert exit_code == 0

    installed_pac = tmp_path / "out" / "dmm_package" / "CLI_Auto_Replace_Test" / "files" / "character" / "cd_phw_00_lb_00_0182.pac"
    assert installed_pac.read_bytes() == b"REBUILT"


def test_cli_auto_replace_all_covers_multiple_pieces_in_one_package(tmp_path, monkeypatch, fitting_config):
    import zipfile
    from sky2cd import auto_replace
    from sky2cd.meshir import MeshIR, save_meshir
    import numpy as np

    pack_dir = tmp_path / "multi_piece_pack"
    for piece_name in ("boots", "gloves"):
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
        for piece_name in ("boots", "gloves"):
            zf.write(pack_dir / f"{piece_name}.meshir.json", arcname=f"{piece_name}.meshir.json")
            zf.write(pack_dir / f"{piece_name}.meshir.npz", arcname=f"{piece_name}.meshir.npz")

    def _fake_export_donor_obj(cf, pac_bytes, entry_path, out_dir):
        from pathlib import Path as _Path

        obj_path = _Path(out_dir) / f"{_Path(entry_path).stem}.obj"
        obj_path.write_text("v -1 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
        return obj_path

    monkeypatch.setattr(auto_replace.cfb, "load_crimsonforge_modules", lambda home: object())
    monkeypatch.setattr(auto_replace.cfb, "open_vfs", lambda cf, packages_path: object())
    monkeypatch.setattr(auto_replace.cfb, "read_donor_pac_bytes", lambda vfs, entry_path, group: b"ORIG")
    monkeypatch.setattr(auto_replace.cfb, "export_donor_obj", _fake_export_donor_obj)
    monkeypatch.setattr(auto_replace.cfb, "rebuild_pac", lambda cf, obj_path, original: b"REBUILT")
    monkeypatch.setattr(auto_replace.cfb, "read_sidecar_files", lambda vfs, entry_path, group: {})

    exit_code = main([
        "auto-replace-all",
        "--body-config", str(fitting_config),
        "--input", str(zip_path),
        "--piece", "boots=demenissian_elite_leather_lb",
        "--piece", "gloves=proxima_ref_hands",
        "--packages-path", str(tmp_path / "packages"),
        "--crimsonforge-home", str(tmp_path / "crimsonforge"),
        "--title", "CLI Auto Replace All Test",
        "--out", str(tmp_path / "out_all"),
    ])
    assert exit_code == 0

    mod_files = tmp_path / "out_all" / "dmm_package" / "CLI_Auto_Replace_All_Test" / "files" / "character"
    assert (mod_files / "cd_phw_00_lb_00_0182.pac").read_bytes() == b"REBUILT"
    assert (mod_files / "cd_phw_00_hand_00_0146.pac").read_bytes() == b"REBUILT"


def test_cli_auto_replace_all_auto_selects_donors_when_piece_is_omitted(tmp_path, monkeypatch, capsys, fitting_config):
    # Real motivation: --piece used to be required for every single piece,
    # even when the outfit's slots are unambiguous (hood/gloves each have
    # exactly one matching catalog donor) -- omitting --piece entirely
    # should still produce a complete DMM package by auto-selecting donors.
    # (Boots/feet now has two legitimate catalog donors after this session's
    # donor-identity fix -- the real "Damian" boots plus an older
    # reference-mod feet path -- so "hood" is used here instead of "boots"
    # to keep this test exercising the single-unambiguous-candidate case.)
    import zipfile
    from sky2cd import auto_replace
    from sky2cd.meshir import MeshIR, save_meshir
    import numpy as np

    pack_dir = tmp_path / "auto_multi_piece_pack"
    for piece_name in ("hood", "gloves"):
        mesh = MeshIR(
            positions=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
            normals=np.array([[0.0, 0.0, 1.0]] * 3, dtype=np.float32),
            uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
            triangles=np.array([[0, 1, 2]], dtype=np.uint32),
            name=piece_name,
        )
        save_meshir(mesh, pack_dir / f"{piece_name}.meshir.json")

    zip_path = tmp_path / "auto_multi_piece_outfit.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for piece_name in ("hood", "gloves"):
            zf.write(pack_dir / f"{piece_name}.meshir.json", arcname=f"{piece_name}.meshir.json")
            zf.write(pack_dir / f"{piece_name}.meshir.npz", arcname=f"{piece_name}.meshir.npz")

    def _fake_export_donor_obj(cf, pac_bytes, entry_path, out_dir):
        from pathlib import Path as _Path

        obj_path = _Path(out_dir) / f"{_Path(entry_path).stem}.obj"
        obj_path.write_text("v -1 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
        return obj_path

    monkeypatch.setattr(auto_replace.cfb, "load_crimsonforge_modules", lambda home: object())
    monkeypatch.setattr(auto_replace.cfb, "open_vfs", lambda cf, packages_path: object())
    monkeypatch.setattr(auto_replace.cfb, "read_donor_pac_bytes", lambda vfs, entry_path, group: b"ORIG")
    monkeypatch.setattr(auto_replace.cfb, "export_donor_obj", _fake_export_donor_obj)
    monkeypatch.setattr(auto_replace.cfb, "rebuild_pac", lambda cf, obj_path, original: b"REBUILT")
    monkeypatch.setattr(auto_replace.cfb, "read_sidecar_files", lambda vfs, entry_path, group: {})

    # No --piece flags at all: relies on the REAL built-in donor_catalog
    # (this session's "head"/"hands" entries) via sky2cd.donor_auto_select's
    # real filename-keyword guessing.
    exit_code = main([
        "auto-replace-all",
        "--body-config", str(fitting_config),
        "--input", str(zip_path),
        "--packages-path", str(tmp_path / "packages"),
        "--crimsonforge-home", str(tmp_path / "crimsonforge"),
        "--title", "CLI Auto Select Test",
        "--out", str(tmp_path / "out_auto_select"),
    ])
    assert exit_code == 0
    assert "auto-selected a donor per piece" in capsys.readouterr().out

    mod_files = tmp_path / "out_auto_select" / "dmm_package" / "CLI_Auto_Select_Test" / "files" / "character"
    assert (mod_files / "cd_phw_00_hel_00_0146.pac").read_bytes() == b"REBUILT"
    assert (mod_files / "cd_phw_00_hand_00_0146.pac").read_bytes() == b"REBUILT"


def test_cli_blender_handoff_runs_with_fakes(tmp_path, monkeypatch, capsys, fitting_config):
    from sky2cd import blender_handoff
    from sky2cd.meshir import MeshIR, save_meshir
    import numpy as np

    mesh = MeshIR(
        positions=np.array([[0.0, 0.0, 100.0], [1.0, 0.0, 100.0], [0.0, 1.0, 100.0]], dtype=np.float32),
        normals=np.array([[0.0, 1.0, 0.0]] * 3, dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        name="cli_handoff_outfit",
    )
    mesh_path = save_meshir(mesh, tmp_path / "outfit.meshir.json")

    def _fake_export_donor_obj(cf, pac_bytes, entry_path, out_dir):
        from pathlib import Path as _Path

        obj_path = _Path(out_dir) / f"{_Path(entry_path).stem}.obj"
        obj_path.write_text("v -1 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
        return obj_path

    class _FakeResolver:
        def resolve(self, entry_path):
            return "Fake In-Game Name"

    monkeypatch.setattr(blender_handoff.cfb, "load_crimsonforge_modules", lambda home: object())
    monkeypatch.setattr(blender_handoff.cfb, "open_vfs", lambda cf, packages_path: object())
    monkeypatch.setattr(blender_handoff.cfb, "read_donor_pac_bytes", lambda vfs, entry_path, group: b"ORIG")
    monkeypatch.setattr(blender_handoff.cfb, "export_donor_obj", _fake_export_donor_obj)
    monkeypatch.setattr(blender_handoff.cfb, "read_sidecar_files", lambda vfs, entry_path, group: {})
    monkeypatch.setattr(blender_handoff.cfb, "build_item_name_resolver", lambda cf, vfs: _FakeResolver())

    exit_code = main([
        "blender-handoff",
        "--body-config", str(fitting_config),
        "--input", str(mesh_path),
        "--piece", "piece=demenissian_elite_leather_lb",
        "--packages-path", str(tmp_path / "packages"),
        "--crimsonforge-home", str(tmp_path / "crimsonforge"),
        "--out", str(tmp_path / "out_handoff"),
    ])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "artist handoff, NOT a finished conversion" in captured.out
    assert "donor in-game name: Fake In-Game Name" in captured.out

    piece_dir = tmp_path / "out_handoff" / "handoff" / "00_piece"
    assert (piece_dir / "source.obj").is_file()
    assert (piece_dir / "donor" / "donor.obj").is_file()
    assert (piece_dir / "metadata.json").is_file()
    assert (tmp_path / "out_handoff" / "handoff" / "import_script.py").is_file()


def test_cli_blender_handoff_source_only_without_game_paths(tmp_path, capsys, fitting_config):
    from sky2cd.meshir import MeshIR, save_meshir
    import numpy as np

    mesh = MeshIR(
        positions=np.array([[0.0, 0.0, 100.0], [1.0, 0.0, 100.0], [0.0, 1.0, 100.0]], dtype=np.float32),
        normals=np.array([[0.0, 1.0, 0.0]] * 3, dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        name="cli_handoff_source_only",
    )
    mesh_path = save_meshir(mesh, tmp_path / "outfit.meshir.json")

    exit_code = main([
        "blender-handoff",
        "--body-config", str(fitting_config),
        "--input", str(mesh_path),
        "--piece", "piece=demenissian_elite_leather_lb",
        "--out", str(tmp_path / "out_handoff_source_only"),
    ])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "not given" in captured.out or "NOTE:" in captured.out
    piece_dir = tmp_path / "out_handoff_source_only" / "handoff" / "00_piece"
    assert (piece_dir / "source.obj").is_file()
    assert not (piece_dir / "donor").exists()
