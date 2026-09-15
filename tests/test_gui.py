"""Headless tests for the GUI's validation / argument-building layer.

These never construct a tkinter window, so they run on machines without a
display or without tcl/tk installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sky2cd import gui


def test_gui_branding_centers_blender_preview_workflow():
    assert gui.APP_TITLE == "Sky2CD Blender Assistant & Preview Tools"
    assert "artist review required" in gui.AUTO_DONOR_LABEL


def _write(path: Path, text: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_deformer_labels_include_all_three_with_stubs_marked_unavailable():
    labels = gui.deformer_labels()
    assert len(labels) == 3
    assert any("idw" in label and "unavailable" not in label for label in labels)
    assert sum("unavailable" in label for label in labels) == 2


def test_label_to_deformer_round_trips():
    for name, (label, _) in gui.DEFORMERS.items():
        assert gui.label_to_deformer(label) == name


def test_label_to_deformer_rejects_unknown_label():
    with pytest.raises(gui.ValidationError):
        gui.label_to_deformer("not a real deformer")


def test_validate_inputs_builds_request(tmp_path: Path):
    mesh = _write(tmp_path / "outfit.meshir.json", json.dumps({"name": "outfit"}))
    config = _write(tmp_path / "body.json")
    out_dir = tmp_path / "out"

    request = gui.validate_inputs(str(mesh), str(config), str(out_dir), "idw", atlas=True)

    assert request == gui.ConvertRequest(mesh, config, out_dir, "idw", atlas=True)


def test_validate_inputs_accepts_preset_keys(tmp_path: Path):
    mesh = _write(tmp_path / "outfit.nif")
    out_dir = tmp_path / "out"

    req1 = gui.validate_inputs(str(mesh), "fem_kliff", str(out_dir), "idw")
    assert req1.body_config == "fem_kliff"

    req2 = gui.validate_inputs(str(mesh), "Preset: Skyrim Female -> Fem Kliff (Recommended)", str(out_dir), "idw")
    assert req2.body_config == "fem_kliff"


def test_validate_inputs_rejects_unselected_custom_label(tmp_path: Path):
    mesh = _write(tmp_path / "outfit.nif")
    out_dir = tmp_path / "out"
    with pytest.raises(gui.ValidationError, match="Choose a custom body-config JSON file"):
        gui.validate_inputs(str(mesh), gui.CUSTOM_CONFIG_LABEL, str(out_dir), "idw")


@pytest.mark.parametrize("ext", [".7z", ".zip", ".nif", ".json"])
def test_validate_inputs_accepts_supported_extensions(tmp_path: Path, ext: str):
    mesh = _write(tmp_path / f"outfit{ext}")
    config = _write(tmp_path / "body.json")
    out_dir = tmp_path / "out"

    request = gui.validate_inputs(str(mesh), str(config), str(out_dir), "idw")
    assert request.input_path == mesh


@pytest.mark.parametrize("field", ["input", "config", "out"])
def test_validate_inputs_requires_every_field(tmp_path: Path, field: str):
    mesh = str(_write(tmp_path / "outfit.meshir.json"))
    config = str(_write(tmp_path / "body.json"))
    out_dir = str(tmp_path / "out")
    values = {"input": mesh, "config": config, "out": out_dir}
    values[field] = "   "

    with pytest.raises(gui.ValidationError):
        gui.validate_inputs(values["input"], values["config"], values["out"], "idw")


def test_validate_inputs_rejects_missing_input_file(tmp_path: Path):
    config = str(_write(tmp_path / "body.json"))
    with pytest.raises(gui.ValidationError, match="does not exist"):
        gui.validate_inputs(str(tmp_path / "nope.nif"), config, str(tmp_path / "out"), "idw")


def test_validate_inputs_rejects_unsupported_extension(tmp_path: Path):
    mesh = str(_write(tmp_path / "outfit.obj"))
    config = str(_write(tmp_path / "body.json"))
    with pytest.raises(gui.ValidationError, match="Unsupported input format"):
        gui.validate_inputs(mesh, config, str(tmp_path / "out"), "idw")


def test_validate_inputs_rejects_missing_body_config(tmp_path: Path):
    mesh = str(_write(tmp_path / "outfit.meshir.json"))
    with pytest.raises(gui.ValidationError, match="Body-config file does not exist"):
        gui.validate_inputs(mesh, str(tmp_path / "missing.json"), str(tmp_path / "out"), "idw")


def test_validate_inputs_rejects_output_path_that_is_a_file(tmp_path: Path):
    mesh = str(_write(tmp_path / "outfit.meshir.json"))
    config = str(_write(tmp_path / "body.json"))
    out_file = str(_write(tmp_path / "out.txt", "not a folder"))
    with pytest.raises(gui.ValidationError, match="not a folder"):
        gui.validate_inputs(mesh, config, out_file, "idw")


@pytest.mark.parametrize("deformer", ["rigid-mls", "bsw"])
def test_validate_inputs_rejects_stub_deformers(tmp_path: Path, deformer: str):
    mesh = str(_write(tmp_path / "outfit.meshir.json"))
    config = str(_write(tmp_path / "body.json"))
    with pytest.raises(gui.ValidationError, match="not implemented"):
        gui.validate_inputs(mesh, config, str(tmp_path / "out"), deformer)


def test_deformer_availability_matches_pipeline_choices():
    assert gui.deformer_is_available("idw") is True
    assert gui.deformer_is_available("rigid-mls") is False
    assert gui.deformer_is_available("bsw") is False
    with pytest.raises(gui.ValidationError):
        gui.deformer_is_available("nope")


def test_open_folder_rejects_missing_directory(tmp_path: Path):
    with pytest.raises(gui.ValidationError, match="does not exist"):
        gui.open_folder(tmp_path / "missing")


def _make_obj(path: Path) -> Path:
    path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    return path


def test_validate_merge_inputs_builds_request(tmp_path: Path):
    donor = _make_obj(tmp_path / "donor.obj")
    outfit = _make_obj(tmp_path / "outfit.obj")
    out = tmp_path / "merged.obj"

    request = gui.validate_merge_inputs(str(donor), str(outfit), str(out), "0.02", "nearest")

    assert request.donor_path == donor
    assert request.outfit_path == outfit
    assert request.out_path == out
    assert request.shrink_factor == 0.02
    assert request.submesh_strategy == "nearest"


@pytest.mark.parametrize("field", ["donor", "outfit", "out"])
def test_validate_merge_inputs_requires_every_field(tmp_path: Path, field: str):
    donor = _make_obj(tmp_path / "donor.obj")
    outfit = _make_obj(tmp_path / "outfit.obj")
    out = tmp_path / "merged.obj"
    args = {"donor": str(donor), "outfit": str(outfit), "out": str(out)}
    args[field] = ""

    with pytest.raises(gui.ValidationError):
        gui.validate_merge_inputs(args["donor"], args["outfit"], args["out"], "0.02", "nearest")


def test_validate_merge_inputs_rejects_missing_donor_file(tmp_path: Path):
    outfit = _make_obj(tmp_path / "outfit.obj")
    with pytest.raises(gui.ValidationError, match="does not exist"):
        gui.validate_merge_inputs(str(tmp_path / "missing.obj"), str(outfit), str(tmp_path / "out.obj"), "0.02", "nearest")


def test_validate_merge_inputs_rejects_non_obj_donor(tmp_path: Path):
    donor = tmp_path / "donor.txt"
    donor.write_text("not an obj")
    outfit = _make_obj(tmp_path / "outfit.obj")
    with pytest.raises(gui.ValidationError, match=r"\.obj"):
        gui.validate_merge_inputs(str(donor), str(outfit), str(tmp_path / "out.obj"), "0.02", "nearest")


def test_validate_merge_inputs_rejects_bad_shrink_factor(tmp_path: Path):
    donor = _make_obj(tmp_path / "donor.obj")
    outfit = _make_obj(tmp_path / "outfit.obj")
    with pytest.raises(gui.ValidationError, match="number"):
        gui.validate_merge_inputs(str(donor), str(outfit), str(tmp_path / "out.obj"), "not-a-number", "nearest")


def test_validate_merge_inputs_rejects_out_of_range_shrink_factor(tmp_path: Path):
    donor = _make_obj(tmp_path / "donor.obj")
    outfit = _make_obj(tmp_path / "outfit.obj")
    with pytest.raises(gui.ValidationError, match="between 0 and 1"):
        gui.validate_merge_inputs(str(donor), str(outfit), str(tmp_path / "out.obj"), "1.5", "nearest")


def test_validate_merge_inputs_rejects_unknown_submesh_strategy(tmp_path: Path):
    donor = _make_obj(tmp_path / "donor.obj")
    outfit = _make_obj(tmp_path / "outfit.obj")
    with pytest.raises(gui.ValidationError, match="Submesh strategy"):
        gui.validate_merge_inputs(str(donor), str(outfit), str(tmp_path / "out.obj"), "0.02", "blender-magic")


def test_donor_labels_and_parsing():
    labels = gui.donor_labels()
    assert len(labels) >= 2
    assert labels[0] == gui.AUTO_DONOR_LABEL

    assert gui.label_to_donor_id(gui.AUTO_DONOR_LABEL) is None
    assert gui.label_to_donor_id("") is None
    assert gui.label_to_donor_id("Some Item (slot) [demenissian_elite_leather_lb]") == "demenissian_elite_leather_lb"


def test_validate_auto_replace_inputs_builds_request(tmp_path: Path):
    mesh = _write(tmp_path / "outfit.7z")
    pkgs = tmp_path / "packages"
    pkgs.mkdir()
    cf = tmp_path / "CrimsonForge"
    (cf / "core").mkdir(parents=True)
    _write(cf / "core" / "mesh_importer.py", "# mock")
    out_dir = tmp_path / "dmm_out"

    req = gui.validate_auto_replace_inputs(
        input_path=str(mesh),
        body_config_or_preset="fem_kliff",
        packages_path=str(pkgs),
        crimsonforge_home=str(cf),
        out_dir=str(out_dir),
        title="Custom Title",
        donor_label_or_id=gui.AUTO_DONOR_LABEL,
        atlas=True,
    )

    assert req.input_path == mesh
    assert req.body_config == "fem_kliff"
    assert req.packages_path == pkgs
    assert req.crimsonforge_home == cf
    assert req.out_dir == out_dir
    assert req.title == "Custom Title"
    assert req.donor_id is None
    assert req.atlas is True


def test_build_gui_donor_suggestion_reuses_ranker_and_writes_json(tmp_path: Path):
    result = gui.build_gui_donor_suggestion("Boots_1.nif", tmp_path)

    assert result.donor_id == "damian_elite_leather_boots"
    assert result.display_name == "Damian's Elite Uniform Leather Boots (feet)"
    assert result.json_path == tmp_path / "donor_suggestion.json"
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["recommended_donor_id"] == result.donor_id
    assert payload["recommended"]["rank"] == 1
    assert payload["alternates"][0]["rank"] == 2
    assert "does not guarantee fit" in payload["artist_validation_boundary"]
    assert "game-ready conversion" in payload["artist_validation_boundary"]
    assert "Recommended donor:" in result.text
    assert "Alternates:" in result.text
    assert "Artist-validation boundary" in result.text


def test_build_gui_donor_suggestion_requires_piece_and_output(tmp_path: Path):
    with pytest.raises(gui.ValidationError, match="recognizable outfit piece"):
        gui.build_gui_donor_suggestion("", tmp_path)
    with pytest.raises(gui.ValidationError, match="output folder"):
        gui.build_gui_donor_suggestion("Boots_1.nif", "")


def test_game_tool_path_status_keeps_preview_available_without_optional_tools(tmp_path: Path):
    text, color = gui.game_tool_path_status("", "")
    assert "Blender preview still works" in text
    assert "needed only for live donor verification" in text
    assert "optional DMM packaging" in text
    assert color != "red"

    packages = tmp_path / "packages"
    packages.mkdir()
    text, _ = gui.game_tool_path_status(str(packages), "")
    assert "Blender preview still works" in text
    assert "Add CrimsonForge" in text


def test_theme_palette_dark_and_light_have_matching_keys_but_differ():
    dark = gui.theme_palette(True)
    light = gui.theme_palette(False)
    assert dark.keys() == light.keys()
    assert dark != light
    # Every palette must define these so _apply_theme never KeyErrors.
    required_keys = {
        "bg",
        "fg",
        "entry_bg",
        "entry_fg",
        "button_bg",
        "log_bg",
        "log_fg",
        "accent",
        "select_bg",
    }
    assert required_keys <= dark.keys()


def test_theme_palette_returns_independent_copies():
    first = gui.theme_palette(True)
    first["bg"] = "#000000"
    second = gui.theme_palette(True)
    assert second["bg"] != "#000000"


def test_theme_palette_includes_polish_and_tooltip_keys():
    """Modernization-pass keys (headings, cards, tooltip colors) must exist in both themes."""
    polish_keys = {
        "card_bg",
        "border",
        "heading_fg",
        "muted_fg",
        "accent_fg",
        "tooltip_bg",
        "tooltip_fg",
    }
    dark = gui.theme_palette(True)
    light = gui.theme_palette(False)
    assert polish_keys <= dark.keys()
    assert polish_keys <= light.keys()


def test_tooltips_registry_covers_key_controls():
    """Every high-value control called out by the tooltip request must have hover text."""
    expected_keys = {
        "raw_input",
        "raw_out",
        "raw_convert",
        "suggest_piece",
        "suggest_donor",
        "suggestion_open_folder",
        "dark_mode",
        "raw_preset",
        "ar_packages_path",
        "ar_crimsonforge_home",
        "dmm_generate",
        "merge_donor",
        "merge_outfit",
        "merge_out",
        "merge_btn",
    }
    assert expected_keys <= gui.TOOLTIPS.keys()
    for key, text in gui.TOOLTIPS.items():
        assert isinstance(text, str) and text.strip(), key
        assert len(text) < 260, f"tooltip {key!r} is too long to read at a glance"


def test_manual_donor_merge_tooltips_explain_how_to_obtain_files():
    """The 'how do I get a donor .obj' question must be answered in the tooltip text."""
    donor_text = gui.TOOLTIPS["merge_donor"].lower()
    assert "exported" in donor_text or "export" in donor_text
    outfit_text = gui.TOOLTIPS["merge_outfit"].lower()
    assert "create preview files" in outfit_text or "source.obj" in outfit_text


def test_tooltip_text_never_claims_guaranteed_fit_or_game_ready_output():
    """Donor-suggestion tooltips must keep the honest starting-point boundary."""
    suggest_text = gui.TOOLTIPS["suggest_donor"].lower()
    assert "does not guarantee" in suggest_text
    assert "game-ready" in suggest_text
    assert "guaranteed" not in suggest_text
    assert "certifies" not in suggest_text


def test_tooltip_helper_schedules_and_cancels_without_a_display():
    """_Tooltip only needs objects that look like widgets; verify the show/hide contract."""

    class _FakeWidget:
        def __init__(self):
            self.bound: dict[str, list] = {}
            self.after_calls: list[tuple[int, object]] = []
            self.cancelled: list[object] = []

        def bind(self, sequence, func, add=None):
            self.bound.setdefault(sequence, []).append(func)

        def after(self, delay_ms, callback):
            token = object()
            self.after_calls.append((delay_ms, callback))
            return token

        def after_cancel(self, token):
            self.cancelled.append(token)

    widget = _FakeWidget()
    tip = gui._Tooltip(widget, "hello", lambda: gui.theme_palette(True))

    assert "<Enter>" in widget.bound
    assert "<Leave>" in widget.bound
    assert "<ButtonPress>" in widget.bound

    # Simulate hovering: schedule then immediately leaving before the delay fires.
    widget.bound["<Enter>"][0]()
    assert widget.after_calls
    widget.bound["<Leave>"][0]()
    assert widget.cancelled
    assert tip._popup is None


def test_user_settings_defaults_to_dark_mode():
    from sky2cd.settings import UserSettings

    assert UserSettings().dark_mode is True


def test_load_settings_defaults_dark_mode_true_when_missing(tmp_path: Path, monkeypatch):
    from sky2cd import settings as settings_mod

    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(settings_mod, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(settings_mod, "SETTINGS_FILE", settings_file)
    settings_file.write_text("{}", encoding="utf-8")

    loaded = settings_mod.load_settings()
    assert loaded.dark_mode is True


def test_settings_dark_mode_round_trips(tmp_path: Path, monkeypatch):
    from sky2cd import settings as settings_mod

    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(settings_mod, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(settings_mod, "SETTINGS_FILE", settings_file)

    settings_mod.save_settings(settings_mod.UserSettings(dark_mode=False))
    reloaded = settings_mod.load_settings()
    assert reloaded.dark_mode is False


def test_on_toggle_theme_persists_and_applies(monkeypatch):
    """Exercise the toggle handler's logic without needing a real Tk display."""
    from sky2cd.settings import UserSettings

    calls = {"apply_theme": None, "saved": None, "logged": []}

    class _FakeVar:
        def __init__(self, value: bool):
            self._value = value

        def get(self) -> bool:
            return self._value

    class _Dummy:
        def __init__(self):
            self.settings = UserSettings(dark_mode=True)
            self.dark_mode_var = _FakeVar(False)

        def _apply_theme(self, dark: bool) -> None:
            calls["apply_theme"] = dark

        def _log(self, text: str) -> None:
            calls["logged"].append(text)

    def _fake_save_settings(settings):
        calls["saved"] = settings.dark_mode

    monkeypatch.setattr(gui, "save_settings", _fake_save_settings)

    dummy = _Dummy()
    gui._Sky2cdApp._on_toggle_theme(dummy)

    assert calls["apply_theme"] is False
    assert calls["saved"] is False
    assert dummy.settings.dark_mode is False
    assert any("light mode" in text for text in calls["logged"])


def test_active_gui_is_blender_first_not_legacy_override():
    assert gui._Sky2cdApp.__doc__ is not None
    assert "Blender-preview preparation" in gui._Sky2cdApp.__doc__
    assert gui._LegacySky2cdApp is not gui._Sky2cdApp
    assert callable(getattr(gui._Sky2cdApp, "mainloop", None))
    assert callable(getattr(gui._LegacySky2cdApp, "mainloop", None))
    assert callable(getattr(gui._Sky2cdApp, "_apply_theme", None))
    assert callable(getattr(gui._Sky2cdApp, "_on_toggle_theme", None))


def test_gui_run_invokes_app_mainloop(monkeypatch):
    called = {"instantiated": False, "mainloop": False}

    class _FakeApp:
        def __init__(self):
            called["instantiated"] = True

        def mainloop(self):
            called["mainloop"] = True

    monkeypatch.setattr(gui, "_Sky2cdApp", _FakeApp)
    exit_code = gui.run()
    assert exit_code == 0
    assert called["instantiated"] is True
    assert called["mainloop"] is True


def test_sky2cd_app_mainloop_delegates_to_root():
    class _DummyApp:
        def __init__(self):
            class _FakeRoot:
                def __init__(self):
                    self.called = False

                def mainloop(self):
                    self.called = True

            self.root = _FakeRoot()

    # Bind the actual method from _Sky2cdApp to verify contract
    dummy = _DummyApp()
    gui._Sky2cdApp.mainloop(dummy)
    assert dummy.root.called is True


def test_validate_auto_replace_inputs_rejects_missing_paths(tmp_path: Path):
    mesh = _write(tmp_path / "outfit.7z")
    out_dir = tmp_path / "dmm_out"

    with pytest.raises(gui.ValidationError, match="Game packages"):
        gui.validate_auto_replace_inputs(str(mesh), "fem_kliff", "", "", str(out_dir))
