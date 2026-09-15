"""User settings persistence for sky2cd GUI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SETTINGS_DIR = Path.home() / ".sky2cd"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


@dataclass
class UserSettings:
    last_input_dir: str = ""
    last_config_dir: str = ""
    last_output_dir: str = ""
    default_preset: str = "fem_kliff"
    deformer: str = "idw"
    crimsonforge_home: str = ""
    packages_path: str = ""
    dark_mode: bool = True


def get_settings_path() -> Path:
    return SETTINGS_FILE


def load_settings() -> UserSettings:
    """Load settings from user home directory, returning defaults if missing or corrupted."""
    if not SETTINGS_FILE.is_file():
        return UserSettings()
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return UserSettings(
            last_input_dir=str(data.get("last_input_dir", "")),
            last_config_dir=str(data.get("last_config_dir", "")),
            last_output_dir=str(data.get("last_output_dir", "")),
            default_preset=str(data.get("default_preset", "fem_kliff")),
            deformer=str(data.get("deformer", "idw")),
            crimsonforge_home=str(data.get("crimsonforge_home", "")),
            packages_path=str(data.get("packages_path", "")),
            dark_mode=bool(data.get("dark_mode", True)),
        )
    except Exception:
        return UserSettings()


def save_settings(settings: UserSettings) -> None:
    """Save user settings to disk."""
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    except Exception:
        pass  # Silently avoid failing if user home is write-restricted
