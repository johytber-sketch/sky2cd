"""Unit tests for user settings persistence."""

from __future__ import annotations

import json
from pathlib import Path

from sky2cd.settings import UserSettings, load_settings, save_settings


def test_user_settings_round_trip(tmp_path: Path, monkeypatch):
    test_settings_file = tmp_path / "settings.json"
    monkeypatch.setattr("sky2cd.settings.SETTINGS_DIR", tmp_path)
    monkeypatch.setattr("sky2cd.settings.SETTINGS_FILE", test_settings_file)

    initial = load_settings()
    assert initial.default_preset == "fem_kliff"
    assert initial.last_input_dir == ""
    assert initial.dark_mode is True

    modified = UserSettings(
        last_input_dir="C:/mods",
        last_config_dir="C:/configs",
        last_output_dir="C:/out",
        default_preset="cd_vanilla_female",
        dark_mode=False,
    )
    save_settings(modified)

    assert test_settings_file.is_file()
    reloaded = load_settings()
    assert reloaded.last_input_dir == "C:/mods"
    assert reloaded.last_config_dir == "C:/configs"
    assert reloaded.last_output_dir == "C:/out"
    assert reloaded.default_preset == "cd_vanilla_female"
    assert reloaded.dark_mode is False
