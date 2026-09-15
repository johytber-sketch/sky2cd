"""Built-in body presets for the sky2cd pipeline."""

from __future__ import annotations

from importlib import resources
import json
from pathlib import Path
from typing import Any

from sky2cd.meshir import MeshIR, save_meshir
from sky2cd.deform.validation import validate_body_pair

_PRESETS_DATA_PKG = "sky2cd.data.presets"

PRESET_DEFINITIONS: dict[str, dict[str, Any]] = {
    "fem_kliff": {
        "display_name": "Preset: Skyrim Female -> Fem Kliff (Geometry preview only)",
        "config_filename": "fem_kliff.json",
    },
    "cd_vanilla_female": {
        "display_name": "Preset: Skyrim Female -> CD Vanilla Female (Geometry preview only)",
        "config_filename": "cd_vanilla_female.json",
    },
}

DEFAULT_PRESET_KEY = "fem_kliff"


def get_default_preset_key() -> str:
    """Return the default preset identifier."""
    return DEFAULT_PRESET_KEY


def list_presets() -> dict[str, str]:
    """Return a mapping of preset key -> display name."""
    return {k: v["display_name"] for k, v in PRESET_DEFINITIONS.items()}


def get_presets_dir() -> Path:
    """Return the absolute Path to the presets package data directory."""
    try:
        traversable = resources.files(_PRESETS_DATA_PKG)
        # In Python 3.10+ importlib.resources.files may return a Path or zip Traversable.
        # If it's a standard Path or running under PyInstaller (where sys._MEIPASS exists):
        if hasattr(traversable, "_path"):
            return Path(traversable._path)  # type: ignore[attr-defined]
        return Path(str(traversable))
    except Exception:
        # Fallback to relative package directory
        return Path(__file__).resolve().parent / "data" / "presets"


def is_preset_key(name_or_key: str) -> bool:
    """Check if the provided name/key corresponds to a known preset."""
    raw = _legacy_preset_label(name_or_key.strip())
    for key, info in PRESET_DEFINITIONS.items():
        if raw.lower() == info["display_name"].lower():
            return True
    norm = raw.lower().replace("-", "_")
    if norm.endswith(".json"):
        norm = norm[:-5]
    return norm in PRESET_DEFINITIONS


def normalize_preset_key(name_or_key: str) -> str:
    """Normalize a string or display name into a canonical preset key."""
    raw = _legacy_preset_label(name_or_key.strip())
    for key, info in PRESET_DEFINITIONS.items():
        if raw.lower() == info["display_name"].lower():
            return key
    norm = raw.lower().replace("-", "_")
    if norm.endswith(".json"):
        norm = norm[:-5]
    if norm in PRESET_DEFINITIONS:
        return norm
    raise ValueError(f"Unknown preset key or name: '{name_or_key}'")


def _legacy_preset_label(value: str) -> str:
    aliases = {
        "preset: skyrim female -> fem kliff (recommended)": "fem_kliff",
        "preset: skyrim female -> cd vanilla female": "cd_vanilla_female",
    }
    return aliases.get(value.lower(), value)


def require_fitting_config(config: dict[str, Any]) -> None:
    if config.get("geometry_mode", "body_fit") != "body_fit":
        raise ValueError(
            "Geometry/alignment preview only: bundled presets do not contain authentic "
            "body references. Automatic PAC/DMM packaging is blocked. Supply a custom "
            "source body and its corresponding target reshape, validate the fit in Blender, "
            "and verify target rig/weights before attempting an experimental rebuild."
        )


def resolve_body_config(path_or_preset: str | Path | dict[str, Any]) -> dict[str, Any]:
    """Resolve a preset key, JSON file path, or config dict into a loaded config dict.

    All mesh paths (source_body, target_body, sidecar) are resolved to absolute paths.
    """
    if isinstance(path_or_preset, dict):
        return _resolve_mesh_paths(path_or_preset, Path.cwd())

    str_val = str(path_or_preset).strip()
    if is_preset_key(str_val):
        key = normalize_preset_key(str_val)
        preset_info = PRESET_DEFINITIONS[key]
        presets_dir = get_presets_dir()
        config_path = presets_dir / preset_info["config_filename"]
        if not config_path.is_file():
            # If files were not initialized, ensure fallback creation or load
            raise FileNotFoundError(f"Preset configuration file not found: {config_path}")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        return _resolve_mesh_paths(config, presets_dir)

    # Otherwise treat as custom file path
    file_path = Path(str_val)
    if not file_path.is_file():
        raise FileNotFoundError(f"Body-config file or preset not found: '{path_or_preset}'")

    config = json.loads(file_path.read_text(encoding="utf-8"))
    return _resolve_mesh_paths(config, file_path.parent)


def _resolve_mesh_paths(config: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    resolved = dict(config)
    for field in ("source_body", "target_body", "sidecar"):
        if field in resolved and resolved[field]:
            p = Path(resolved[field])
            if not p.is_absolute():
                resolved[field] = str((base_dir / p).resolve())
            else:
                resolved[field] = str(p.resolve())
    return resolved


def build_custom_preset(
    source_body: MeshIR,
    target_body: MeshIR,
    name: str,
    out_dir: str | Path,
    *,
    scale: float = 1.0,
    min_clearance: float = 0.001,
    skyrim_slots: list[str] | None = None,
) -> Path:
    """Bake a reusable body-config preset from a source/target body pair.

    This is the "do the Blender/BodySlider body-shape fit once" step: `source_body`
    and `target_body` must be the SAME base mesh topology (same vertex count and
    vertex order) — e.g. a stock CBBE/3BA reference body, and that same mesh
    re-shaped (sculpted, or run through a BodySlider preset) to match the target
    Crimson Desert body's proportions. Once saved, every future outfit built on
    that same source body can be converted with `sky2cd convert --body-config
    <name>.json` and will automatically pick up the same per-vertex displacement
    field via the IDW deformer -- no repeated manual Blender/BodySlider work per
    outfit is needed after this one-time setup.

    Returns the path to the written `<name>.json` config file.
    """
    if source_body.vertex_count != target_body.vertex_count:
        raise ValueError(
            "source_body and target_body must have the same vertex count "
            f"(got {source_body.vertex_count} vs {target_body.vertex_count}) -- "
            "they must be the same base mesh topology, just reshaped."
        )
    if source_body.vertex_count == 0:
        raise ValueError("source_body/target_body must not be empty")
    validate_body_pair(source_body, target_body)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    source_path = save_meshir(source_body, out_path / f"{name}_source_body.meshir.json")
    target_path = save_meshir(target_body, out_path / f"{name}_target_body.meshir.json")

    config = {
        "name": name,
        "geometry_mode": "body_fit",
        "source_body": source_path.name,
        "target_body": target_path.name,
        "scale": scale,
        "min_clearance": min_clearance,
        "skyrim_slots": skyrim_slots or [],
    }
    config_path = out_path / f"{name}.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path
