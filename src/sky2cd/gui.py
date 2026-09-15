"""Tkinter desktop front-end for the sky2cd conversion pipeline.

The windowing code is deliberately isolated from the validation/argument
building logic so the latter can be unit tested on machines without a display
or without tkinter available. ``tkinter`` is imported lazily inside
:func:`run` for the same reason.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path

from sky2cd.crimsonforge_bridge import (
    _looks_like_crimsonforge_home,
    find_crimsonforge_home,
    find_packages_path,
)
from sky2cd.donor_catalog import BUILTIN_DONOR_CATALOG, DonorEntry, get_entry, list_catalog
from sky2cd.presets import (
    DEFAULT_PRESET_KEY,
    PRESET_DEFINITIONS,
    is_preset_key,
    list_presets,
    normalize_preset_key,
)
from sky2cd.settings import UserSettings, load_settings, save_settings

APP_TITLE = "Sky2CD Blender Assistant & Preview Tools"
CUSTOM_CONFIG_LABEL = "Custom body-config JSON..."
AUTO_DONOR_LABEL = "Auto-select by inferred slot (artist review required)"

#: Deformer id -> (menu label, available). Only IDW is actually implemented;
#: the others are stubs in sky2cd.deform and must not be selectable.
DEFORMERS: dict[str, tuple[str, bool]] = {
    "idw": ("idw - inverse distance weighting", True),
    "rigid-mls": ("rigid-mls - unavailable (not implemented)", False),
    "bsw": ("bsw - unavailable (not implemented)", False),
}

SUPPORTED_INPUT_SUFFIXES = (".nif", ".json", ".7z", ".zip")


class ValidationError(ValueError):
    """Raised when the values entered in the GUI cannot form a valid run."""


@dataclass(frozen=True)
class ConvertRequest:
    """A validated set of pipeline arguments, ready to hand to ``convert``."""

    input_path: Path
    body_config: str | Path
    out_dir: Path
    deformer: str
    atlas: bool = False


@dataclass(frozen=True)
class MergeRequest:
    """A validated set of arguments for the experimental donor-merge tool."""

    donor_path: Path
    outfit_path: Path
    out_path: Path
    shrink_factor: float
    submesh_strategy: str


@dataclass(frozen=True)
class AutoReplaceGuiRequest:
    """Validated arguments for the optional experimental DMM packaging path."""

    input_path: Path
    body_config: str | Path
    packages_path: Path
    crimsonforge_home: Path
    out_dir: Path
    title: str
    author: str = "sky2cd"
    version: str = "1.0.0"
    donor_id: str | None = None
    deformer: str = "idw"
    atlas: bool = True
    max_workers: int = -1


@dataclass(frozen=True)
class GuiDonorSuggestion:
    """Human-readable and persistent outputs produced by the GUI action."""

    donor_id: str
    display_name: str
    text: str
    json_path: Path


MERGE_SUBMESH_STRATEGIES = ["nearest", "append"]

#: Color palettes for the two supported GUI themes. Kept as plain dicts (no
#: tkinter import) so palette selection is unit-testable on machines without
#: a display. Semantic warning/status colors ("#9a6700" amber, "green", etc.)
#: used elsewhere are intentionally left theme-neutral; they read fine on
#: both backgrounds.
THEME_LIGHT: dict[str, str] = {
    "bg": "#f5f6f8",
    "fg": "#1a1a1a",
    "entry_bg": "#ffffff",
    "entry_fg": "#1a1a1a",
    "button_bg": "#e4e6ea",
    "log_bg": "#ffffff",
    "log_fg": "#1a1a1a",
    "accent": "#3a7ca5",
    "accent_fg": "#ffffff",
    "select_bg": "#cde4f3",
    "card_bg": "#ffffff",
    "border": "#d5d8dd",
    "heading_fg": "#12314f",
    "muted_fg": "#5b6472",
    "tooltip_bg": "#2b2b2b",
    "tooltip_fg": "#f2f2f2",
}

THEME_DARK: dict[str, str] = {
    "bg": "#1b1c1e",
    "fg": "#e6e6e6",
    "entry_bg": "#2a2b2e",
    "entry_fg": "#e6e6e6",
    "button_bg": "#333437",
    "log_bg": "#232427",
    "log_fg": "#d9d9d9",
    "accent": "#3d8bd4",
    "accent_fg": "#ffffff",
    "select_bg": "#2f5b82",
    "card_bg": "#222325",
    "border": "#3a3b3e",
    "heading_fg": "#8fc4ff",
    "muted_fg": "#a3a7ad",
    "tooltip_bg": "#f2f2f2",
    "tooltip_fg": "#1a1a1a",
}


def theme_palette(dark: bool) -> dict[str, str]:
    """Return the color palette for the requested theme.

    Pure lookup, no tkinter import, so it can be unit tested headlessly.
    """
    return dict(THEME_DARK if dark else THEME_LIGHT)


#: Concise hover-help text for the GUI's most confusing/high-value controls.
#: Kept as a plain dict (no tkinter import) so its content is unit-testable
#: on machines without a display. Keys are stable identifiers passed to
#: ``_Sky2cdApp._tip`` when building widgets.
TOOLTIPS: dict[str, str] = {
    "raw_input": "Skyrim outfit to prepare: .nif, .meshir.json, .7z, or .zip. You can also drag a file onto the window.",
    "raw_out": "Folder where preview files (source.obj, diagnostic PAC, report) are written. Created if missing.",
    "raw_convert": "Creates Blender-preview geometry only. Not a fitted, rigged, or game-ready outfit.",
    "raw_preset": "Target body used only for geometry/axis conversion during preview, not a validated fit.",
    "raw_custom_config": "Optional custom body-config JSON, used instead of a built-in preset.",
    "raw_deformer": "Geometry deformation method. Only 'idw' is implemented; the others are disabled stubs.",
    "suggest_piece": "Outfit piece filename or path (e.g. Boots_1.nif) used to rank donor candidates.",
    "suggest_donor": "Ranks donor candidates for this piece as a starting target. Does not guarantee fit, "
    "rig, animation, or game-ready output.",
    "suggestion_open_folder": "Open the folder containing the generated donor_suggestion.json.",
    "dark_mode": "Toggle dark/light theme. Applies immediately and is remembered next time.",
    "ar_input": "Skyrim outfit archive/mesh to package (.7z, .zip, .nif). Optional advanced/experimental path.",
    "ar_preset": "Target body preset used for the optional DMM package geometry conversion.",
    "ar_donor": "Donor item used as the optional DMM packaging starting target; pick via Suggest donor or manually.",
    "ar_out": "Working/output folder for the optional DMM package build.",
    "ar_packages_path": "Path to the real game's packages/ folder. Needed only for live donor verification, "
    "in-game names, and DMM packaging; Blender preview works without it.",
    "ar_crimsonforge_home": "Path to a CrimsonForge install. Needed only for live donor verification, in-game "
    "names, and DMM packaging; Blender preview works without it.",
    "dmm_generate": "Builds an experimental DMM package from an artist-rebuilt donor. Does not certify a "
    "wearable or game-ready result on its own.",
    "dmm_open_folder": "Open the folder containing the generated DMM package.",
    "merge_donor": "A donor body/armor part's raw .obj mesh, exported from the actual game/CrimsonForge or from "
    "a Blender scene you built around a Suggest donor recommendation. This is not auto-fetched.",
    "merge_outfit": "The outfit piece .obj produced by 'Create Preview Files' above (source.obj in its output "
    "folder), or another .obj you've prepared in Blender.",
    "merge_out": "Where the merged .obj is written. Still a preview mesh: re-check fit, clipping, and weights "
    "in Blender before treating it as game-ready.",
    "merge_btn": "Combines the two .obj files into one mesh for further Blender work. Does not rig, weight, "
    "or validate fit/clipping/animation.",
}


class _Tooltip:  # pragma: no cover - requires a display to exercise
    """A small delayed hover tooltip for a single ttk/tk widget.

    Reads live colors from ``palette_getter`` at show time so it stays
    correct across a dark/light toggle without needing to be rebuilt.
    """

    _DELAY_MS = 500

    def __init__(self, widget, text: str, palette_getter) -> None:
        self._widget = widget
        self._text = text
        self._palette_getter = palette_getter
        self._after_id = None
        self._popup = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after_id = self._widget.after(self._DELAY_MS, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self._widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self) -> None:
        if self._popup is not None:
            return
        try:
            import tkinter as tk

            x = self._widget.winfo_rootx() + 12
            y = self._widget.winfo_rooty() + self._widget.winfo_height() + 8
            palette = self._palette_getter()
            popup = tk.Toplevel(self._widget)
            popup.wm_overrideredirect(True)
            popup.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                popup,
                text=self._text,
                justify="left",
                background=palette["tooltip_bg"],
                foreground=palette["tooltip_fg"],
                relief="solid",
                borderwidth=1,
                wraplength=320,
                font=("Segoe UI", 8),
                padx=6,
                pady=3,
            )
            label.pack()
            self._popup = popup
        except Exception:
            self._popup = None

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._popup is not None:
            try:
                self._popup.destroy()
            except Exception:
                pass
            self._popup = None


def deformer_labels() -> list[str]:
    """Menu labels in display order, including the unavailable stubs."""
    return [label for label, _ in DEFORMERS.values()]


def label_to_deformer(label: str) -> str:
    for name, (text, _) in DEFORMERS.items():
        if text == label:
            return name
    raise ValidationError(f"Unknown deformer selection: {label!r}")


def deformer_is_available(name: str) -> bool:
    entry = DEFORMERS.get(name)
    if entry is None:
        raise ValidationError(f"Unknown deformer: {name!r}")
    return entry[1]


def preset_labels() -> list[str]:
    """Return combobox choices for body preset selection."""
    labels = [info["display_name"] for info in PRESET_DEFINITIONS.values()]
    labels.append(CUSTOM_CONFIG_LABEL)
    return labels


def donor_labels() -> list[str]:
    """Return combobox choices for in-game transmog target selection."""
    labels = [AUTO_DONOR_LABEL]
    for entry in list_catalog():
        labels.append(f"{entry.display_name} ({entry.slot}) [{entry.id}]")
    return labels


def label_to_donor_id(label: str) -> str | None:
    if not label or label.strip() == AUTO_DONOR_LABEL:
        return None
    trimmed = label.strip()
    if "[" in trimmed and trimmed.endswith("]"):
        return trimmed.split("[")[-1].rstrip("]").strip()
    return trimmed


def build_gui_donor_suggestion(
    piece_name_or_path: str,
    out_dir: str | Path,
    *,
    limit: int = 3,
) -> GuiDonorSuggestion:
    """Build the GUI recommendation using the canonical ranking and JSON writer."""
    piece = piece_name_or_path.strip()
    if not piece:
        raise ValidationError(
            "Enter a recognizable outfit piece name or file, such as Dress_1.nif or Boots_1.nif."
        )
    output_text = str(out_dir).strip()
    if not output_text:
        raise ValidationError("Choose an output folder before suggesting a donor.")

    from sky2cd.donor_recommendation import (
        format_recommendations,
        rank_donors,
        write_recommendation_json,
    )

    try:
        recommendations = rank_donors(piece)
        json_path = write_recommendation_json(
            Path(output_text) / "donor_suggestion.json",
            piece,
            recommendations,
            limit=limit,
        )
    except (ValueError, OSError) as exc:
        raise ValidationError(str(exc)) from exc
    top = recommendations[0]
    return GuiDonorSuggestion(
        donor_id=top.entry.id,
        display_name=top.display_name,
        text=format_recommendations(piece, recommendations, limit=limit),
        json_path=json_path,
    )


def game_tool_path_status(packages_path: str, crimsonforge_home: str) -> tuple[str, str]:
    """Return first-run guidance without implying preview depends on game tools."""
    packages_ok = bool(packages_path and Path(packages_path).is_dir())
    crimsonforge_ok = bool(
        crimsonforge_home and _looks_like_crimsonforge_home(Path(crimsonforge_home))
    )
    preview_note = "Blender preview still works without these paths."
    if packages_ok and crimsonforge_ok:
        return (
            "Game packages and CrimsonForge found. Live donor verification, in-game names, "
            "and optional DMM packaging are available; artist validation is still required.",
            "green",
        )
    if packages_ok:
        return (
            f"{preview_note} Add CrimsonForge for live donor verification, in-game names, "
            "and optional DMM packaging.",
            "#9a6700",
        )
    if crimsonforge_ok:
        return (
            f"{preview_note} Add the game packages folder for live donor verification, "
            "in-game names, and optional DMM packaging.",
            "#9a6700",
        )
    return (
        f"{preview_note} Game and CrimsonForge paths are needed only for live donor "
        "verification, in-game names, and optional DMM packaging.",
        "#9a6700",
    )


def validate_inputs(
    input_path: str,
    body_config_or_preset: str,
    out_dir: str,
    deformer: str,
    atlas: bool = False,
) -> ConvertRequest:
    """Turn raw GUI field strings into a :class:`ConvertRequest`.

    Raises :class:`ValidationError` with a message meant to be shown verbatim
    to the user.
    """
    if not input_path.strip():
        raise ValidationError("Choose a Skyrim outfit input file (.nif, .meshir.json, .7z, or .zip).")
    if not body_config_or_preset.strip():
        raise ValidationError("Choose a body target preset or custom body-config JSON file.")
    if not out_dir.strip():
        raise ValidationError("Choose an output folder.")

    mesh = Path(input_path.strip())
    output = Path(out_dir.strip())

    if not mesh.is_file():
        raise ValidationError(f"Input file does not exist: {mesh}")
    if mesh.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
        raise ValidationError(f"Unsupported input format '{mesh.suffix}'. Expected a .nif, .meshir.json, .7z, or .zip file.")
    if output.exists() and not output.is_dir():
        raise ValidationError(f"Output path exists but is not a folder: {output}")

    if not deformer_is_available(deformer):
        raise ValidationError(
            f"The '{deformer}' deformer is a stub and not implemented yet. Select 'idw' instead."
        )

    # Validate body config / preset
    config_str = body_config_or_preset.strip()
    if is_preset_key(config_str):
        resolved_config = normalize_preset_key(config_str)
    elif config_str == CUSTOM_CONFIG_LABEL:
        raise ValidationError("Choose a custom body-config JSON file using the Browse button.")
    else:
        config_path = Path(config_str)
        if not config_path.is_file():
            raise ValidationError(f"Body-config file does not exist: {config_path}")
        if config_path.suffix.lower() != ".json":
            raise ValidationError(f"Body-config must be a .json file, got '{config_path.suffix}'.")
        resolved_config = config_path

    return ConvertRequest(input_path=mesh, body_config=resolved_config, out_dir=output, deformer=deformer, atlas=atlas)


def validate_auto_replace_inputs(
    input_path: str,
    body_config_or_preset: str,
    packages_path: str,
    crimsonforge_home: str,
    out_dir: str,
    title: str = "",
    author: str = "sky2cd",
    version: str = "1.0.0",
    donor_label_or_id: str | None = None,
    deformer: str = "idw",
    atlas: bool = True,
    max_workers: int = -1,
) -> AutoReplaceGuiRequest:
    """Turn raw GUI strings for Auto-Replace into an :class:`AutoReplaceGuiRequest`."""
    if not input_path.strip():
        raise ValidationError("Choose a Skyrim outfit input file (.nif, .meshir.json, .7z, or .zip).")
    if not body_config_or_preset.strip():
        raise ValidationError("Choose a body target preset or custom body-config JSON file.")
    if not packages_path.strip():
        raise ValidationError(
            "Game packages/ folder not found. Please locate your Crimson Desert 'packages/' directory."
        )
    if not crimsonforge_home.strip():
        raise ValidationError(
            "CrimsonForge install not found. Please locate your CrimsonForge directory."
        )
    if not out_dir.strip():
        raise ValidationError("Choose an output folder for the DMM package.")

    mesh = Path(input_path.strip())
    if not mesh.is_file():
        raise ValidationError(f"Input file does not exist: {mesh}")
    if mesh.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
        raise ValidationError(f"Unsupported input format '{mesh.suffix}'. Expected a .nif, .meshir.json, .7z, or .zip file.")

    pkgs = Path(packages_path.strip())
    if not pkgs.is_dir():
        raise ValidationError(f"Game packages directory does not exist: {pkgs}")
    if (pkgs / "packages").is_dir():
        pkgs = pkgs / "packages"

    cf_home = Path(crimsonforge_home.strip())
    if not cf_home.is_dir() or not _looks_like_crimsonforge_home(cf_home):
        raise ValidationError(
            f"'{cf_home}' does not look like a CrimsonForge installation (missing core/mesh_importer.py)."
        )

    output = Path(out_dir.strip())
    if output.exists() and not output.is_dir():
        raise ValidationError(f"Output path exists but is not a folder: {output}")

    if not deformer_is_available(deformer):
        raise ValidationError(f"The '{deformer}' deformer is not implemented. Select 'idw'.")

    config_str = body_config_or_preset.strip()
    if is_preset_key(config_str):
        resolved_config = normalize_preset_key(config_str)
    elif config_str == CUSTOM_CONFIG_LABEL:
        raise ValidationError("Choose a custom body-config JSON file using the Browse button.")
    else:
        config_path = Path(config_str)
        if not config_path.is_file():
            raise ValidationError(f"Body-config file does not exist: {config_path}")
        resolved_config = config_path

    mod_title = title.strip()
    if not mod_title:
        base_name = mesh.stem
        if base_name.endswith(".meshir"):
            base_name = base_name[:-7]
        mod_title = f"{base_name.replace('_', ' ').title()} Mod"

    donor_id = label_to_donor_id(donor_label_or_id or "")

    return AutoReplaceGuiRequest(
        input_path=mesh,
        body_config=resolved_config,
        packages_path=pkgs,
        crimsonforge_home=cf_home,
        out_dir=output,
        title=mod_title,
        author=author.strip() or "sky2cd",
        version=version.strip() or "1.0.0",
        donor_id=donor_id,
        deformer=deformer,
        atlas=atlas,
        max_workers=max_workers,
    )


def validate_merge_inputs(
    donor_path: str,
    outfit_path: str,
    out_path: str,
    shrink_factor_str: str,
    submesh_strategy: str,
) -> MergeRequest:
    """Turn raw GUI field strings into a :class:`MergeRequest`.

    Raises :class:`ValidationError` with a message meant to be shown verbatim
    to the user.
    """
    if not donor_path.strip():
        raise ValidationError("Choose a donor item .obj (e.g. exported from CrimsonForge).")
    if not outfit_path.strip():
        raise ValidationError("Choose a converted outfit .obj (from a prior sky2cd conversion).")
    if not out_path.strip():
        raise ValidationError("Choose an output path for the merged .obj.")

    donor = Path(donor_path.strip())
    outfit = Path(outfit_path.strip())
    out = Path(out_path.strip())

    if not donor.is_file():
        raise ValidationError(f"Donor OBJ does not exist: {donor}")
    if donor.suffix.lower() != ".obj":
        raise ValidationError(f"Donor must be a .obj file, got '{donor.suffix}'.")
    if not outfit.is_file():
        raise ValidationError(f"Outfit OBJ does not exist: {outfit}")
    if outfit.suffix.lower() != ".obj":
        raise ValidationError(f"Outfit must be a .obj file, got '{outfit.suffix}'.")

    try:
        shrink_factor = float(shrink_factor_str.strip())
    except ValueError:
        raise ValidationError(f"Shrink factor must be a number, got '{shrink_factor_str}'.")
    if not (0.0 < shrink_factor < 1.0):
        raise ValidationError("Shrink factor must be between 0 and 1 (exclusive), e.g. 0.02.")

    if submesh_strategy not in MERGE_SUBMESH_STRATEGIES:
        raise ValidationError(f"Submesh strategy must be one of {MERGE_SUBMESH_STRATEGIES}, got '{submesh_strategy}'.")

    return MergeRequest(
        donor_path=donor,
        outfit_path=outfit,
        out_path=out,
        shrink_factor=shrink_factor,
        submesh_strategy=submesh_strategy,
    )


def open_folder(path: Path) -> None:
    """Reveal a folder using the platform file manager."""
    path = Path(path)
    if not path.is_dir():
        raise ValidationError(f"Folder does not exist yet: {path}")
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606  - intentional shell-less explorer launch
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def crash_log_path() -> Path:
    """Where uncaught GUI errors are recorded (the windowed exe has no console)."""
    log_dir = Path.home() / ".sky2cd"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "crash.log"


def _write_crash_log(context: str, detail: str) -> None:
    try:
        import datetime

        with crash_log_path().open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== {datetime.datetime.now().isoformat()} | {context} ===\n{detail}\n")
    except OSError:
        pass


def _legacy_run() -> int:
    """Retained legacy launcher; the Blender-first ``run`` above is active."""
    try:
        import tkinter  # noqa: F401
    except ImportError as exc:
        sys.stderr.write(
            "sky2cd-gui: tkinter is not available in this Python installation.\n"
            f"  ({exc})\n"
            "Install a CPython build that includes tcl/tk, or use the command line tool 'sky2cd' instead.\n"
        )
        return 1

    def _log_uncaught(exc_type, exc_value, exc_tb) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write_crash_log("uncaught exception", detail)

    sys.excepthook = _log_uncaught
    threading.excepthook = lambda args: _log_uncaught(args.exc_type, args.exc_value, args.exc_traceback)

    try:
        app = _Sky2cdApp()
        app.mainloop()
    except Exception:
        _write_crash_log("fatal error during startup/mainloop", traceback.format_exc())
        raise
    return 0


class _Sky2cdApp:  # pragma: no cover - requires a display to exercise
    """The main window prioritizes Blender-preview preparation over optional packaging."""

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        self._ttk = ttk
        self._events: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._last_out_dir: Path | None = None
        self._last_dmm_mod_dir: Path | None = None
        self._last_report: Path | None = None
        self._last_suggestion_path: Path | None = None
        self.settings: UserSettings = load_settings()

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.minsize(920, 760)
        self.root.geometry("960x800")
        self.root.report_callback_exception = self._report_callback_exception

        # Modern default typeface for a 2026 look; falls back gracefully if
        # "Segoe UI Variable" isn't installed (older Windows/Linux/macOS).
        self._base_font_family = "Segoe UI Variable Text"
        try:
            import tkinter.font as tkfont

            if self._base_font_family not in tkfont.families(self.root):
                self._base_font_family = "Segoe UI"
        except Exception:
            self._base_font_family = "Segoe UI"
        self._base_font = (self._base_font_family, 10)
        try:
            import tkinter.font as tkfont

            tkfont.nametofont("TkDefaultFont").configure(family=self._base_font_family, size=10)
            tkfont.nametofont("TkTextFont").configure(family=self._base_font_family, size=10)
            tkfont.nametofont("TkHeadingFont").configure(family=self._base_font_family, size=10, weight="bold")
        except Exception:
            pass

        # Auto-detect game paths and crimsonforge
        detected_cf = find_crimsonforge_home(self.settings.crimsonforge_home or None)
        detected_pkgs = find_packages_path(self.settings.packages_path or None)

        # Optional experimental DMM packaging vars
        self.ar_input_var = tk.StringVar(value="")
        default_preset_info = PRESET_DEFINITIONS.get(
            self.settings.default_preset, PRESET_DEFINITIONS[DEFAULT_PRESET_KEY]
        )
        self.ar_preset_var = tk.StringVar(value=default_preset_info["display_name"])
        self.ar_custom_config_var = tk.StringVar(value="")
        self.ar_donor_var = tk.StringVar(value=AUTO_DONOR_LABEL)
        self.ar_suggest_piece_var = tk.StringVar(value="")
        self.ar_title_var = tk.StringVar(value="")
        self.ar_packages_var = tk.StringVar(value=str(detected_pkgs) if detected_pkgs else "")
        self.ar_crimsonforge_var = tk.StringVar(value=str(detected_cf) if detected_cf else "")
        self.ar_out_var = tk.StringVar(value=self.settings.last_output_dir or "")
        self.ar_atlas_var = tk.BooleanVar(value=True)
        self.ar_parallel_var = tk.BooleanVar(value=True)

        # Primary Blender preview vars
        self.raw_input_var = tk.StringVar(value="")
        self.raw_preset_var = tk.StringVar(value=default_preset_info["display_name"])
        self.raw_custom_config_var = tk.StringVar(value="")
        self.raw_out_var = tk.StringVar(value=self.settings.last_output_dir or "")
        self.raw_deformer_var = tk.StringVar(value=DEFORMERS["idw"][0])
        self.raw_atlas_var = tk.BooleanVar(value=False)

        # Merge tool vars
        self.merge_donor_var = tk.StringVar()
        self.merge_outfit_var = tk.StringVar()
        self.merge_out_var = tk.StringVar()
        self.merge_shrink_var = tk.StringVar(value="0.02")
        self.merge_strategy_var = tk.StringVar(value=MERGE_SUBMESH_STRATEGIES[0])

        self.status_var = tk.StringVar(value="Ready.")
        self.dark_mode_var = tk.BooleanVar(value=self.settings.dark_mode)
        self._palette = theme_palette(self.settings.dark_mode)

        self._build_widgets()
        self._apply_theme(self.settings.dark_mode)
        self._update_auto_detection_status()
        self._init_dnd()
        self.root.after(100, self._drain_events)

    def _init_dnd(self) -> None:
        try:
            import windnd

            def on_drop(files):
                for f in files:
                    if isinstance(f, bytes):
                        f = f.decode("utf-8", errors="replace")
                    p = Path(f)
                    if p.is_dir():
                        self.ar_out_var.set(str(p))
                        self.raw_out_var.set(str(p))
                        self.settings.last_output_dir = str(p)
                        save_settings(self.settings)
                        self._log(f"[Drop] Set output folder: {p}")
                    elif p.suffix.lower() in {".7z", ".zip", ".nif"}:
                        self.ar_input_var.set(str(p))
                        self.raw_input_var.set(str(p))
                        self.settings.last_input_dir = str(p.parent)
                        if not self.ar_title_var.get():
                            clean_name = p.stem.replace("_", " ").title()
                            self.ar_title_var.set(f"{clean_name} Mod")
                        save_settings(self.settings)
                        self._log(f"[Drop] Set outfit input: {p}")
                    elif p.suffix.lower() == ".json":
                        if "body" in p.name.lower() or "config" in p.name.lower():
                            self.ar_preset_var.set(CUSTOM_CONFIG_LABEL)
                            self.ar_custom_config_var.set(str(p))
                            self.raw_preset_var.set(CUSTOM_CONFIG_LABEL)
                            self.raw_custom_config_var.set(str(p))
                            self.settings.last_config_dir = str(p.parent)
                            save_settings(self.settings)
                            self._log(f"[Drop] Set custom body config: {p}")
                        else:
                            self.ar_input_var.set(str(p))
                            self.raw_input_var.set(str(p))
                            self.settings.last_input_dir = str(p.parent)
                            save_settings(self.settings)
                            self._log(f"[Drop] Set outfit input: {p}")

            windnd.hook_dropfiles(self.root, func=on_drop)
        except Exception:
            pass

    def _build_widgets(self) -> None:
        tk, ttk = self._tk, self._ttk
        main_container = ttk.Frame(self.root, padding=16)
        main_container.pack(fill="both", expand=True)

        header = ttk.Frame(main_container)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="Sky2CD", style="Heading.TLabel", font=(self._base_font_family, 18, "bold")).pack(
            side="left"
        )
        ttk.Label(
            header,
            text="   Blender-first outfit prep · donor suggestions · optional DMM packaging",
            style="Muted.TLabel",
        ).pack(side="left")

        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill="both", expand=True)

        # TAB 1: Blender-preview preparation
        self.tab_raw = ttk.Frame(self.notebook, padding=18)
        self.notebook.add(self.tab_raw, text="  Blender Prep & Preview  ")
        self._build_raw_tab(self.tab_raw)

        # TAB 2: Optional experimental packaging
        self.tab_dmm = ttk.Frame(self.notebook, padding=18)
        self.notebook.add(self.tab_dmm, text="  Advanced DMM Packaging (Experimental)  ")
        self._build_dmm_tab(self.tab_dmm)

        # Bottom Area: Progress, Status & Log (shared across tabs)
        bottom_frame = ttk.Frame(main_container, padding=(0, 14, 0, 0))
        bottom_frame.pack(fill="both", expand=True)

        self.progress = ttk.Progressbar(bottom_frame, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))

        status_bar = ttk.Frame(bottom_frame)
        status_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(status_bar, textvariable=self.status_var, font=(self._base_font_family, 10, "bold")).pack(
            side="left"
        )
        self.dark_mode_check = ttk.Checkbutton(
            status_bar,
            text="🌙 Dark mode",
            variable=self.dark_mode_var,
            command=self._on_toggle_theme,
        )
        self.dark_mode_check.pack(side="right")
        self._tip(self.dark_mode_check, "dark_mode")

        log_frame = ttk.Frame(bottom_frame)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_frame,
            height=10,
            wrap="word",
            state="disabled",
            font=("Cascadia Mono", 9),
            borderwidth=1,
            relief="flat",
            padx=8,
            pady=6,
        )
        self.log.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scroll.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scroll.set)

        self._log(
            "Sky2CD ready.\n"
            "• Blender Prep & Preview: convert source geometry for artist inspection in Blender.\n"
            "  Output is a preview/mockup, not a fitted, rigged, or game-ready outfit.\n"
            "• Advanced DMM Packaging: optional experimental tooling for an artist-rebuilt,\n"
            "  independently validated asset; it does not certify wearable game output.\n"
        )

    def _on_toggle_theme(self) -> None:
        """Apply the toggled theme immediately and persist the preference."""
        dark = bool(self.dark_mode_var.get())
        self._apply_theme(dark)
        self.settings.dark_mode = dark
        save_settings(self.settings)
        self._log(f"Theme set to {'dark' if dark else 'light'} mode.")

    def _apply_theme(self, dark: bool) -> None:
        """Style the window for the requested theme without requiring a restart."""
        ttk = self._ttk
        palette = theme_palette(dark)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass  # "clam" ships with CPython's Tk; fall back to whatever is active

        style.configure(".", background=palette["bg"], foreground=palette["fg"], font=self._base_font)
        style.configure("TFrame", background=palette["bg"])
        style.configure("TLabel", background=palette["bg"], foreground=palette["fg"])
        style.configure(
            "TLabelframe",
            background=palette["card_bg"],
            foreground=palette["fg"],
            bordercolor=palette["border"],
            relief="flat",
            borderwidth=1,
        )
        style.configure("TLabelframe.Label", background=palette["card_bg"], foreground=palette["heading_fg"])
        style.configure(
            "TButton",
            background=palette["button_bg"],
            foreground=palette["fg"],
            borderwidth=0,
            focuscolor=palette["bg"],
            padding=(14, 8),
        )
        style.map(
            "TButton",
            background=[("active", palette["select_bg"]), ("disabled", palette["button_bg"])],
            foreground=[("disabled", palette["muted_fg"])],
        )
        style.configure(
            "TCheckbutton",
            background=palette["bg"],
            foreground=palette["fg"],
            focuscolor=palette["bg"],
        )
        style.map("TCheckbutton", background=[("active", palette["bg"])])
        style.configure("TNotebook", background=palette["bg"], borderwidth=0, tabmargins=(0, 8, 0, 0))
        style.configure(
            "TNotebook.Tab",
            background=palette["bg"],
            foreground=palette["muted_fg"],
            padding=(20, 10),
            font=(self._base_font_family, 10, "bold"),
            borderwidth=0,
            focuscolor=palette["bg"],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", palette["accent"]), ("!selected", palette["card_bg"])],
            foreground=[("selected", palette["accent_fg"]), ("!selected", palette["muted_fg"])],
        )
        style.configure(
            "TEntry",
            fieldbackground=palette["entry_bg"],
            foreground=palette["entry_fg"],
            insertcolor=palette["fg"],
            bordercolor=palette["border"],
            lightcolor=palette["border"],
            darkcolor=palette["border"],
            borderwidth=1,
            relief="flat",
            padding=(8, 6),
        )
        style.configure(
            "TCombobox",
            fieldbackground=palette["entry_bg"],
            foreground=palette["entry_fg"],
            background=palette["button_bg"],
            bordercolor=palette["border"],
            arrowcolor=palette["fg"],
            borderwidth=1,
            relief="flat",
            padding=(6, 4),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette["entry_bg"])],
            foreground=[("readonly", palette["entry_fg"])],
        )
        style.configure(
            "Horizontal.TProgressbar",
            background=palette["accent"],
            troughcolor=palette["card_bg"],
            borderwidth=0,
            thickness=8,
        )
        style.configure("TScrollbar", background=palette["button_bg"], troughcolor=palette["bg"], borderwidth=0)
        style.configure("TSeparator", background=palette["border"])

        # Modern-polish styles: section headings, grouped "card" frames, and
        # a primary/accent button style for the main preview action. Kept
        # flat (no groove/ridge relief) with generous padding for a less
        # dated look while staying pure ttk/tk (no extra GUI framework).
        style.configure(
            "Heading.TLabel",
            background=palette["bg"],
            foreground=palette["heading_fg"],
            font=(self._base_font_family, 13, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background=palette["bg"],
            foreground=palette["muted_fg"],
            font=(self._base_font_family, 9),
        )
        style.configure(
            "Card.TLabelframe",
            background=palette["card_bg"],
            bordercolor=palette["border"],
            relief="flat",
            borderwidth=1,
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=palette["card_bg"],
            foreground=palette["heading_fg"],
            font=(self._base_font_family, 10, "bold"),
        )
        style.configure(
            "Accent.TButton",
            background=palette["accent"],
            foreground=palette["accent_fg"],
            font=(self._base_font_family, 10, "bold"),
            padding=(18, 10),
            borderwidth=0,
            focuscolor=palette["accent"],
        )
        style.map(
            "Accent.TButton",
            background=[("active", palette["accent"]), ("disabled", palette["button_bg"])],
            foreground=[("disabled", palette["muted_fg"])],
        )

        # Combobox dropdown listboxes are plain Tk widgets and aren't styled by ttk.Style.
        self.root.option_add("*TCombobox*Listbox.background", palette["entry_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground", palette["entry_fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", palette["select_bg"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", palette["entry_fg"])

        self.root.configure(background=palette["bg"])
        if hasattr(self, "log"):
            self.log.configure(
                background=palette["log_bg"],
                foreground=palette["log_fg"],
                insertbackground=palette["fg"],
                selectbackground=palette["select_bg"],
                highlightthickness=1,
                highlightbackground=palette["border"],
                highlightcolor=palette["border"],
            )
        self._dark_mode = dark
        self._palette = palette

    def _tip(self, widget, key: str) -> None:
        """Attach a hover tooltip from :data:`TOOLTIPS` to ``widget``."""
        text = TOOLTIPS.get(key)
        if not text:
            return
        _Tooltip(widget, text, lambda: self._palette)

    def _build_dmm_tab(self, parent) -> None:
        ttk = self._ttk
        parent.columnconfigure(1, weight=1)

        ttk.Label(
            parent,
            text="Advanced DMM Packaging — optional & experimental",
            style="Heading.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))
        ttk.Label(
            parent,
            text="For artists who have already rebuilt and validated a donor-based .pac. "
            "Does not certify a wearable or game-ready result.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        # Row 2: Outfit input
        self._file_row(parent, 2, "Skyrim Outfit (.7z/.zip/.nif):", self.ar_input_var, self._browse_ar_input, "ar_input")

        # Row 3: Target Body Preset
        ttk.Label(parent, text="Body Target Preset:").grid(row=3, column=0, sticky="w", pady=6)
        self.ar_preset_combo = ttk.Combobox(
            parent,
            textvariable=self.ar_preset_var,
            values=preset_labels(),
            state="readonly",
        )
        self.ar_preset_combo.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=6)
        self.ar_preset_combo.bind("<<ComboboxSelected>>", self._on_ar_preset_change)
        self._tip(self.ar_preset_combo, "ar_preset")

        # Row 4: Custom config (hidden/disabled unless chosen)
        ttk.Label(parent, text="Custom Body Config:").grid(row=4, column=0, sticky="w", pady=6)
        self.ar_custom_entry = ttk.Entry(parent, textvariable=self.ar_custom_config_var, state="disabled")
        self.ar_custom_entry.grid(row=4, column=1, sticky="ew", padx=6, pady=6)
        self.ar_custom_btn = ttk.Button(parent, text="Browse...", command=self._browse_ar_config, state="disabled")
        self.ar_custom_btn.grid(row=4, column=2, sticky="w", pady=6)

        # Row 5: Donor suggestion input and action
        ttk.Label(parent, text="Piece name/file for suggestion:").grid(row=5, column=0, sticky="w", pady=6)
        suggest_entry = ttk.Entry(parent, textvariable=self.ar_suggest_piece_var)
        suggest_entry.grid(row=5, column=1, sticky="ew", padx=6, pady=6)
        self._tip(suggest_entry, "suggest_piece")
        suggest_actions = ttk.Frame(parent)
        suggest_actions.grid(row=5, column=2, sticky="w", pady=6)
        self.suggest_donor_btn = ttk.Button(
            suggest_actions,
            text="Suggest donor",
            command=self._suggest_donor,
        )
        self.suggest_donor_btn.pack(side="left")
        self._tip(self.suggest_donor_btn, "suggest_donor")
        self.suggestion_open_btn = ttk.Button(
            suggest_actions,
            text="Open JSON folder",
            command=self._open_suggestion_folder,
            state="disabled",
        )
        self.suggestion_open_btn.pack(side="left", padx=(6, 0))
        self._tip(self.suggestion_open_btn, "suggestion_open_folder")

        # Row 6: Optional donor target selected by the recommendation or user
        ttk.Label(parent, text="Optional donor starting target:").grid(row=6, column=0, sticky="w", pady=6)
        self.ar_donor_combo = ttk.Combobox(
            parent,
            textvariable=self.ar_donor_var,
            values=donor_labels(),
            state="readonly",
        )
        self.ar_donor_combo.grid(row=6, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=6)
        self._tip(self.ar_donor_combo, "ar_donor")

        ttk.Label(
            parent,
            text="Starting target only. Artist validation required; DMM packaging is optional.",
            foreground="#9a6700",
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 6))

        # Row 8: Mod title and output directory
        ttk.Label(parent, text="Optional Mod Package Title:").grid(row=8, column=0, sticky="w", pady=6)
        ttk.Entry(parent, textvariable=self.ar_title_var).grid(row=8, column=1, sticky="ew", padx=6, pady=6)
        self._file_row(parent, 9, "Working / Output Folder:", self.ar_out_var, self._browse_ar_out, "ar_out")

        # Row 10: Auto-detected Game Paths (Collapsible / Group Box)
        paths_frame = ttk.LabelFrame(parent, text="⚙️ Game & Tool Paths (Auto-Detected)", padding=8, style="Card.TLabelframe")
        paths_frame.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        paths_frame.columnconfigure(1, weight=1)

        self._file_row(
            paths_frame, 0, "Game 'packages/' folder:", self.ar_packages_var, self._browse_packages, "ar_packages_path"
        )
        self._file_row(
            paths_frame,
            1,
            "CrimsonForge folder:",
            self.ar_crimsonforge_var,
            self._browse_crimsonforge,
            "ar_crimsonforge_home",
        )

        self.detect_status_lbl = ttk.Label(paths_frame, text="Checking paths...", style="Muted.TLabel")
        self.detect_status_lbl.grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # Row 11: Options
        opts_frame = ttk.Frame(parent)
        opts_frame.grid(row=11, column=0, columnspan=3, sticky="w", pady=6)

        ttk.Checkbutton(
            opts_frame,
            text="Auto-pack textures into atlas (Blender-Free 1-material donor mode)",
            variable=self.ar_atlas_var,
        ).pack(side="left", padx=(0, 16))

        ttk.Checkbutton(
            opts_frame,
            text="Parallel multi-core rebuild (Fast)",
            variable=self.ar_parallel_var,
        ).pack(side="left")

        # Row 12: Action Buttons
        act_frame = ttk.Frame(parent)
        act_frame.grid(row=12, column=0, columnspan=3, sticky="w", pady=(8, 4))

        self.dmm_gen_btn = ttk.Button(
            act_frame,
            text="Generate Optional DMM Package (Experimental)",
            command=self._start_dmm_generate,
        )
        self.dmm_gen_btn.pack(side="left")
        self._tip(self.dmm_gen_btn, "dmm_generate")

        self.dmm_open_btn = ttk.Button(
            act_frame,
            text="📂 Open DMM Mod Folder",
            command=self._open_dmm_mod_folder,
            state="disabled",
        )
        self.dmm_open_btn.pack(side="left", padx=6)
        self._tip(self.dmm_open_btn, "dmm_open_folder")

    def _build_raw_tab(self, parent) -> None:
        ttk = self._ttk
        parent.columnconfigure(1, weight=1)

        # Raw convert section
        ttk.Label(parent, text="Blender Prep & Preview", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 2)
        )
        ttk.Label(
            parent,
            text="PREVIEW ONLY — Blender preparation; artist validation required",
            font=("Segoe UI", 9, "bold"),
            foreground="#9a6700",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._file_row(
            parent, 2, "Outfit input (.nif/.json/.7z):", self.raw_input_var, self._browse_raw_input, "raw_input"
        )

        ttk.Label(parent, text="Body target preset:").grid(row=3, column=0, sticky="w", pady=6)
        self.raw_preset_combo = ttk.Combobox(
            parent,
            textvariable=self.raw_preset_var,
            values=preset_labels(),
            state="readonly",
        )
        self.raw_preset_combo.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=6)
        self.raw_preset_combo.bind("<<ComboboxSelected>>", self._on_raw_preset_change)
        self._tip(self.raw_preset_combo, "raw_preset")

        ttk.Label(parent, text="Custom body config:").grid(row=4, column=0, sticky="w", pady=6)
        self.raw_custom_entry = ttk.Entry(parent, textvariable=self.raw_custom_config_var, state="disabled")
        self.raw_custom_entry.grid(row=4, column=1, sticky="ew", padx=6, pady=6)
        self.raw_custom_btn = ttk.Button(parent, text="Browse...", command=self._browse_raw_config, state="disabled")
        self.raw_custom_btn.grid(row=4, column=2, sticky="w", pady=6)
        self._tip(self.raw_custom_entry, "raw_custom_config")
        self._tip(self.raw_custom_btn, "raw_custom_config")

        self._file_row(parent, 5, "Output folder:", self.raw_out_var, self._browse_raw_out, "raw_out")

        ttk.Label(parent, text="Deformer:").grid(row=6, column=0, sticky="w", pady=6)
        self.raw_deformer_box = ttk.Combobox(
            parent,
            textvariable=self.raw_deformer_var,
            values=deformer_labels(),
            state="readonly",
            width=36,
        )
        self.raw_deformer_box.grid(row=6, column=1, sticky="w", padx=6, pady=6)
        self._tip(self.raw_deformer_box, "raw_deformer")

        raw_acts = ttk.Frame(parent)
        raw_acts.grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 10))
        self.raw_convert_btn = ttk.Button(
            raw_acts, text="Create Preview Files", command=self._start_raw_convert, style="Accent.TButton"
        )
        self.raw_convert_btn.pack(side="left")
        self._tip(self.raw_convert_btn, "raw_convert")
        self.raw_report_btn = ttk.Button(raw_acts, text="Show Report", command=self._show_report, state="disabled")
        self.raw_report_btn.pack(side="left", padx=6)
        self.raw_folder_btn = ttk.Button(raw_acts, text="Open Output", command=self._open_output, state="disabled")
        self.raw_folder_btn.pack(side="left")

        # Donor merge section
        ttk.Separator(parent, orient="horizontal").grid(row=8, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        ttk.Label(parent, text="Manual Donor Merge (Merge outfit .obj onto donor .obj)", style="Heading.TLabel").grid(
            row=9, column=0, columnspan=3, sticky="w", pady=(0, 2)
        )
        ttk.Label(
            parent,
            text="For artists merging geometry by hand outside Blender. Not required for the Blender workflow above.",
            style="Muted.TLabel",
        ).grid(row=10, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._file_row(parent, 11, "Donor item .obj:", self.merge_donor_var, self._browse_merge_donor, "merge_donor")
        self._file_row(parent, 12, "Outfit .obj:", self.merge_outfit_var, self._browse_merge_outfit, "merge_outfit")
        self._file_row(parent, 13, "Merged output .obj:", self.merge_out_var, self._browse_merge_out, "merge_out")

        merge_acts = ttk.Frame(parent)
        merge_acts.grid(row=14, column=0, columnspan=3, sticky="w", pady=6)
        self.merge_btn = ttk.Button(merge_acts, text="Merge OBJ", command=self._start_merge)
        self.merge_btn.pack(side="left")
        self._tip(self.merge_btn, "merge_btn")

    def _file_row(self, parent, row: int, label: str, var, command, tip_key: str | None = None) -> None:
        ttk = self._ttk
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", padx=6, pady=5)
        browse_btn = ttk.Button(parent, text="Browse...", command=command)
        browse_btn.grid(row=row, column=2, sticky="w", pady=5)
        if tip_key:
            self._tip(entry, tip_key)
            self._tip(browse_btn, tip_key)

    def _update_auto_detection_status(self) -> None:
        text, foreground = game_tool_path_status(
            self.ar_packages_var.get(),
            self.ar_crimsonforge_var.get(),
        )
        self.detect_status_lbl.configure(text=text, foreground=foreground)

    def _on_ar_preset_change(self, _event=None) -> None:
        is_custom = self.ar_preset_var.get() == CUSTOM_CONFIG_LABEL
        state = "normal" if is_custom else "disabled"
        self.ar_custom_entry.configure(state=state)
        self.ar_custom_btn.configure(state=state)
        selected = self.ar_preset_var.get()
        if is_preset_key(selected):
            self.settings.default_preset = normalize_preset_key(selected)
            save_settings(self.settings)

    def _on_raw_preset_change(self, _event=None) -> None:
        is_custom = self.raw_preset_var.get() == CUSTOM_CONFIG_LABEL
        state = "normal" if is_custom else "disabled"
        self.raw_custom_entry.configure(state=state)
        self.raw_custom_btn.configure(state=state)
        selected = self.raw_preset_var.get()
        if is_preset_key(selected):
            self.settings.default_preset = normalize_preset_key(selected)
            save_settings(self.settings)

    def _browse_ar_input(self) -> None:
        from tkinter import filedialog

        init_dir = self.settings.last_input_dir or None
        path = filedialog.askopenfilename(
            title="Select Skyrim outfit archive or mesh",
            initialdir=init_dir,
            filetypes=[
                ("Supported outfit files", "*.7z *.zip *.nif *.json"),
                ("Mod archives (.7z, .zip)", "*.7z *.zip"),
                ("Skyrim NIF (*.nif)", "*.nif"),
                ("MeshIR JSON (*.json)", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.ar_input_var.set(path)
            self.raw_input_var.set(path)
            self.ar_suggest_piece_var.set(Path(path).name)
            self.settings.last_input_dir = str(Path(path).parent)
            if not self.ar_title_var.get():
                clean_name = Path(path).stem.replace("_", " ").title()
                self.ar_title_var.set(f"{clean_name} Mod")
            save_settings(self.settings)

    def _browse_raw_input(self) -> None:
        self._browse_ar_input()

    def _browse_ar_config(self) -> None:
        from tkinter import filedialog

        init_dir = self.settings.last_config_dir or self.settings.last_input_dir or None
        path = filedialog.askopenfilename(
            title="Select custom body config JSON",
            initialdir=init_dir,
            filetypes=[("Body config JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.ar_preset_var.set(CUSTOM_CONFIG_LABEL)
            self.ar_custom_config_var.set(path)
            self.settings.last_config_dir = str(Path(path).parent)
            save_settings(self.settings)

    def _browse_raw_config(self) -> None:
        from tkinter import filedialog

        init_dir = self.settings.last_config_dir or self.settings.last_input_dir or None
        path = filedialog.askopenfilename(
            title="Select custom body config JSON",
            initialdir=init_dir,
            filetypes=[("Body config JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.raw_preset_var.set(CUSTOM_CONFIG_LABEL)
            self.raw_custom_config_var.set(path)
            self.settings.last_config_dir = str(Path(path).parent)
            save_settings(self.settings)

    def _browse_ar_out(self) -> None:
        from tkinter import filedialog

        init_dir = self.settings.last_output_dir or self.settings.last_input_dir or None
        path = filedialog.askdirectory(title="Select Mod Output Folder", initialdir=init_dir)
        if path:
            self.ar_out_var.set(path)
            self.raw_out_var.set(path)
            self.settings.last_output_dir = str(Path(path))
            save_settings(self.settings)

    def _browse_raw_out(self) -> None:
        self._browse_ar_out()

    def _browse_packages(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory(title="Select Crimson Desert 'packages' Folder")
        if path:
            self.ar_packages_var.set(path)
            self.settings.packages_path = str(Path(path))
            save_settings(self.settings)
            self._update_auto_detection_status()

    def _browse_crimsonforge(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory(title="Select CrimsonForge Install Folder")
        if path:
            self.ar_crimsonforge_var.set(path)
            self.settings.crimsonforge_home = str(Path(path))
            save_settings(self.settings)
            self._update_auto_detection_status()

    def _browse_merge_donor(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="Select donor item .obj (e.g. exported from CrimsonForge)",
            filetypes=[("Wavefront OBJ", "*.obj"), ("All files", "*.*")],
        )
        if path:
            self.merge_donor_var.set(path)

    def _browse_merge_outfit(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="Select converted outfit .obj",
            filetypes=[("Wavefront OBJ", "*.obj"), ("All files", "*.*")],
        )
        if path:
            self.merge_outfit_var.set(path)

    def _browse_merge_out(self) -> None:
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(
            title="Save merged .obj as",
            defaultextension=".obj",
            filetypes=[("Wavefront OBJ", "*.obj"), ("All files", "*.*")],
        )
        if path:
            self.merge_out_var.set(path)

    def _suggest_donor(self) -> None:
        from tkinter import messagebox

        piece = self.ar_suggest_piece_var.get().strip()
        if not piece and self.ar_input_var.get().strip():
            piece = Path(self.ar_input_var.get().strip()).name
            self.ar_suggest_piece_var.set(piece)
        try:
            suggestion = build_gui_donor_suggestion(piece, self.ar_out_var.get())
        except ValidationError as exc:
            self.status_var.set("Donor suggestion needs a recognizable piece name and output folder.")
            self._log(f"Donor suggestion unavailable: {exc}")
            messagebox.showerror(APP_TITLE, str(exc))
            return

        matching_label = next(
            (
                label
                for label in donor_labels()
                if label_to_donor_id(label) == suggestion.donor_id
            ),
            None,
        )
        if matching_label:
            self.ar_donor_var.set(matching_label)
        self._last_suggestion_path = suggestion.json_path
        self.suggestion_open_btn.configure(state="normal")
        self.status_var.set("Donor suggested — starting target only; artist validation required.")
        self._log(
            f"\n=== Donor suggested: {suggestion.display_name} ===\n"
            f"{suggestion.text}\n"
            f"JSON reference: {suggestion.json_path}\n"
            "DMM packaging remains optional and experimental.\n"
        )

    def _open_suggestion_folder(self) -> None:
        if self._last_suggestion_path and self._last_suggestion_path.parent.is_dir():
            open_folder(self._last_suggestion_path.parent)

    def _start_dmm_generate(self) -> None:
        from tkinter import messagebox

        preset_str = (
            self.ar_custom_config_var.get()
            if self.ar_preset_var.get() == CUSTOM_CONFIG_LABEL
            else self.ar_preset_var.get()
        )
        try:
            req = validate_auto_replace_inputs(
                input_path=self.ar_input_var.get(),
                body_config_or_preset=preset_str,
                packages_path=self.ar_packages_var.get(),
                crimsonforge_home=self.ar_crimsonforge_var.get(),
                out_dir=self.ar_out_var.get(),
                title=self.ar_title_var.get(),
                donor_label_or_id=self.ar_donor_var.get(),
                atlas=self.ar_atlas_var.get(),
                max_workers=-1 if self.ar_parallel_var.get() else 1,
            )
        except ValidationError as exc:
            self._log(f"ERROR: {exc}")
            self.status_var.set("Fix highlighted settings and try again.")
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self.dmm_gen_btn.configure(state="disabled")
        self.dmm_open_btn.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Experimental DMM packaging — artist validation remains required.")
        self._log(
            f"=== Starting Optional Experimental DMM Packaging ===\n"
            f"  Outfit Input  : {req.input_path.name}\n"
            f"  Target Body   : {req.body_config}\n"
            f"  Transmog Mode : {self.ar_donor_var.get()}\n"
            f"  Atlas Mode    : {req.atlas}\n"
            f"  Parallel      : {req.max_workers != 1}\n"
            f"  Output Dir    : {req.out_dir}\n"
        )
        self._worker = threading.Thread(target=self._dmm_worker, args=(req,), daemon=True)
        self._worker.start()

    def _dmm_worker(self, request: AutoReplaceGuiRequest) -> None:
        try:
            from sky2cd.auto_replace import auto_replace_batch_from_skyrim, auto_replace_from_skyrim

            if request.donor_id is None:
                # Auto-detect / batch mode
                result = auto_replace_batch_from_skyrim(
                    skyrim_mesh_path=request.input_path,
                    body_config_path=request.body_config,
                    pieces=None,
                    packages_path=request.packages_path,
                    crimsonforge_home=request.crimsonforge_home,
                    out_dir=request.out_dir,
                    title=request.title,
                    author=request.author,
                    version=request.version,
                    deformer_name=request.deformer,
                    atlas=request.atlas,
                    max_workers=request.max_workers,
                )
            else:
                donor_entry = get_entry(request.donor_id)
                result = auto_replace_from_skyrim(
                    skyrim_mesh_path=request.input_path,
                    body_config_path=request.body_config,
                    donor=donor_entry,
                    packages_path=request.packages_path,
                    crimsonforge_home=request.crimsonforge_home,
                    out_dir=request.out_dir,
                    title=request.title,
                    author=request.author,
                    version=request.version,
                    deformer_name=request.deformer,
                    atlas=request.atlas,
                )
        except Exception as exc:
            self._events.put(("dmm_error", f"{type(exc).__name__}: {exc}", traceback.format_exc()))
        else:
            self._events.put(("dmm_done", result, request))

    def _start_raw_convert(self) -> None:
        from tkinter import messagebox

        preset_str = (
            self.raw_custom_config_var.get()
            if self.raw_preset_var.get() == CUSTOM_CONFIG_LABEL
            else self.raw_preset_var.get()
        )
        try:
            request = validate_inputs(
                self.raw_input_var.get(),
                preset_str,
                self.raw_out_var.get(),
                label_to_deformer(self.raw_deformer_var.get()),
                atlas=self.raw_atlas_var.get(),
            )
        except ValidationError as exc:
            self._log(f"ERROR: {exc}")
            self.status_var.set("Fix highlighted settings and try again.")
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self.raw_convert_btn.configure(state="disabled")
        self.raw_report_btn.configure(state="disabled")
        self.raw_folder_btn.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Converting raw mesh...")
        self._worker = threading.Thread(target=self._raw_convert_worker, args=(request,), daemon=True)
        self._worker.start()

    def _raw_convert_worker(self, request: ConvertRequest) -> None:
        from sky2cd.pipeline import convert

        try:
            result = convert(
                request.input_path,
                request.body_config,
                request.out_dir,
                request.deformer,
                atlas=request.atlas,
            )
        except Exception as exc:
            self._events.put(("raw_error", f"{type(exc).__name__}: {exc}", traceback.format_exc()))
        else:
            self._events.put(("raw_done", result, request))

    def _start_merge(self) -> None:
        from tkinter import messagebox

        try:
            request = validate_merge_inputs(
                self.merge_donor_var.get(),
                self.merge_outfit_var.get(),
                self.merge_out_var.get(),
                self.merge_shrink_var.get(),
                self.merge_strategy_var.get(),
            )
        except ValidationError as exc:
            self._log(f"ERROR: {exc}")
            self.status_var.set("Fix highlighted settings and try again.")
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self.merge_btn.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Merging OBJ onto donor...")
        self._worker = threading.Thread(target=self._merge_worker_run, args=(request,), daemon=True)
        self._worker.start()

    def _merge_worker_run(self, request: MergeRequest) -> None:
        try:
            from sky2cd.donor_merge import merge_onto_donor
            from sky2cd.exporters.obj_exporter import write_obj
            from sky2cd.importers.obj_importer import read_obj

            donor = read_obj(request.donor_path)
            outfit = read_obj(request.outfit_path)
            merged = merge_onto_donor(
                donor,
                outfit,
                shrink_factor=request.shrink_factor,
                submesh_strategy=request.submesh_strategy,
            )
            out_path = write_obj(merged, request.out_path, axis_convert=False)
        except Exception as exc:
            self._events.put(("merge_error", f"{type(exc).__name__}: {exc}", traceback.format_exc()))
        else:
            self._events.put(("merge_done", out_path, request))

    def _drain_events(self) -> None:
        try:
            while True:
                event = self._events.get_nowait()
                kind, data, req = event[0], event[1], event[2]
                if kind == "dmm_done":
                    self._on_dmm_success(data, req)
                elif kind == "dmm_error":
                    self._on_dmm_failure(data, req)
                elif kind == "raw_done":
                    self._on_raw_success(data, req)
                elif kind == "raw_error":
                    self._on_raw_failure(data, req)
                elif kind == "merge_done":
                    self._on_merge_success(data, req)
                elif kind == "merge_error":
                    self._on_merge_failure(data, req)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _on_dmm_success(self, result, request: AutoReplaceGuiRequest) -> None:
        from sky2cd.auto_replace import BatchAutoReplaceResult

        self.progress.stop()
        self.dmm_gen_btn.configure(state="normal")
        self.dmm_open_btn.configure(state="normal")
        self._last_dmm_mod_dir = Path(result.dmm_package.output_dir)
        self.status_var.set("DMM package created — NOT validated as wearable or game-ready.")

        donor_map = {e.entry_path.lower(): e for e in BUILTIN_DONOR_CATALOG}

        summary_lines = [
            "============================================================",
            "DMM PACKAGE CREATED — ARTIST VALIDATION STILL REQUIRED",
            "============================================================",
            f"📦 Mod Title  : {result.dmm_package.manifest.title}",
            f"📂 Mod Folder : {result.dmm_package.output_dir}",
            "",
            "Packaged donor targets (starting references only):",
        ]

        if isinstance(result, BatchAutoReplaceResult):
            for piece in result.pieces:
                piece_name = Path(piece.selected_mesh_piece).name
                donor_info = donor_map.get(piece.donor_entry_path.lower())
                donor_title = donor_info.display_name if donor_info else piece.donor_entry_path
                summary_lines.append(f"  • {piece_name:<20} ➡️ Replaces in-game: {donor_title}")
            if result.unmatched_mesh_pieces:
                summary_lines.append("\n⚠️ Unmatched pieces (not converted):")
                for un in result.unmatched_mesh_pieces:
                    summary_lines.append(f"  - {un}")
        else:
            piece_name = Path(result.selected_mesh_piece).name
            donor_id = request.donor_id or ""
            donor_title = get_entry(donor_id).display_name if donor_id else "Donor Item"
            summary_lines.append(f"  • {piece_name:<20} ➡️ Replaces in-game: {donor_title}")

        summary_lines.extend([
            "",
            "BOUNDARY: Packaging does not guarantee fit, clipping safety, rig/weights,",
            "animation safety, wearable output, or a game-ready result.",
            "After independent artist validation, optional DMM installation steps:",
            "1. Click 'Open DMM Mod Folder' below.",
            "2. Copy/move this folder into your DMM 'mods/' directory.",
            "3. Enable the mod in DMM and launch Crimson Desert!",
            "============================================================\n",
        ])
        self._log("\n".join(summary_lines))

    def _on_dmm_failure(self, message: str, detail: str) -> None:
        from tkinter import messagebox

        self.progress.stop()
        self.dmm_gen_btn.configure(state="normal")
        self.status_var.set("Mod generation failed.")
        self._log(f"ERROR: {message}\n{detail}")
        _write_crash_log("dmm mod generation failed", detail)
        messagebox.showerror(APP_TITLE, f"{message}\n\nDetails written to {crash_log_path()}")

    def _on_raw_success(self, result, request: ConvertRequest) -> None:
        from sky2cd.pipeline import pretty_report

        self.progress.stop()
        self.raw_convert_btn.configure(state="normal")
        self._last_out_dir = request.out_dir
        self._last_report = Path(result.report_path)
        self.raw_report_btn.configure(state="normal")
        self.raw_folder_btn.configure(state="normal")
        self.status_var.set(
            "Geometry preview only - NOT body fitted."
            if result.report.get("geometry_mode") == "rigid_preview" else "Experimental body fit finished."
        )
        obj_path = result.report.get("output_obj") or (result.report.get("mesh") or {}).get("obj_path")
        self._log(
            f"Wrote {obj_path}\n"
            f"Wrote {result.pac_path}\n"
            f"Wrote {result.report_path}\n\n"
            f"{pretty_report(result.report_path)}\n"
        )

    def _on_raw_failure(self, message: str, detail: str) -> None:
        from tkinter import messagebox

        self.progress.stop()
        self.raw_convert_btn.configure(state="normal")
        self.status_var.set("Raw conversion failed.")
        self._log(f"ERROR: {message}\n{detail}")
        _write_crash_log("raw conversion failed", detail)
        messagebox.showerror(APP_TITLE, f"{message}\n\nDetails written to {crash_log_path()}")

    def _on_merge_success(self, out_path: Path, request: MergeRequest) -> None:
        self.progress.stop()
        self.merge_btn.configure(state="normal")
        self.status_var.set("Merge finished.")
        self._log(f"Wrote merged OBJ: {out_path}\n")

    def _on_merge_failure(self, message: str, detail: str) -> None:
        from tkinter import messagebox

        self.progress.stop()
        self.merge_btn.configure(state="normal")
        self.status_var.set("Merge failed.")
        self._log(f"ERROR: {message}\n{detail}")
        _write_crash_log("merge failed", detail)
        messagebox.showerror(APP_TITLE, f"{message}\n\nDetails written to {crash_log_path()}")

    def _open_dmm_mod_folder(self) -> None:
        if self._last_dmm_mod_dir and self._last_dmm_mod_dir.is_dir():
            open_folder(self._last_dmm_mod_dir)
        elif self.ar_out_var.get() and Path(self.ar_out_var.get()).is_dir():
            open_folder(Path(self.ar_out_var.get()))

    def _open_output(self) -> None:
        if self._last_out_dir and self._last_out_dir.is_dir():
            open_folder(self._last_out_dir)

    def _show_report(self) -> None:
        from tkinter import messagebox

        from sky2cd.pipeline import pretty_report

        if self._last_report and self._last_report.is_file():
            messagebox.showinfo("Conversion Report", pretty_report(self._last_report))

    def _log(self, text: str) -> None:
        import tkinter as tk

        self.log.configure(state="normal")
        self.log.insert(tk.END, text + ("\n" if not text.endswith("\n") else ""))
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def _report_callback_exception(self, exc_type, exc_value, exc_tb) -> None:
        from tkinter import messagebox

        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write_crash_log("tk callback exception", detail)
        message = f"{exc_type.__name__}: {exc_value}"
        self._log(f"ERROR (internal): {message}\n{detail}")
        try:
            messagebox.showerror(APP_TITLE, f"Internal error:\n{message}\n\nDetails written to {crash_log_path()}")
        except Exception:
            pass

    def mainloop(self) -> None:
        self.root.mainloop()


def open_folder(path: Path) -> None:
    """Reveal a folder using the platform file manager."""
    path = Path(path)
    if not path.is_dir():
        raise ValidationError(f"Folder does not exist yet: {path}")
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606  - intentional shell-less explorer launch
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def crash_log_path() -> Path:
    """Where uncaught GUI errors are recorded (the windowed exe has no console)."""
    log_dir = Path.home() / ".sky2cd"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "crash.log"


def _write_crash_log(context: str, detail: str) -> None:
    try:
        import datetime

        with crash_log_path().open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== {datetime.datetime.now().isoformat()} | {context} ===\n{detail}\n")
    except OSError:
        pass  # last resort: nothing more we can safely do without a console


def run() -> int:
    """Launch the desktop window. Returns a process exit code."""
    try:
        import tkinter  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment dependent
        sys.stderr.write(
            "sky2cd-gui: tkinter is not available in this Python installation.\n"
            f"  ({exc})\n"
            "Install a CPython build that includes tcl/tk, or use the command line tool 'sky2cd' instead.\n"
        )
        return 1

    def _log_uncaught(exc_type, exc_value, exc_tb) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write_crash_log("uncaught exception", detail)

    sys.excepthook = _log_uncaught
    threading.excepthook = lambda args: _log_uncaught(args.exc_type, args.exc_value, args.exc_traceback)

    try:
        app = _Sky2cdApp()
        app.mainloop()
    except Exception:
        _write_crash_log("fatal error during startup/mainloop", traceback.format_exc())
        raise
    return 0


class _LegacySky2cdApp:  # pragma: no cover - requires a display to exercise
    """Retained legacy single-tab window; no longer used by :func:`main`."""

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        self._ttk = ttk
        self._events: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._last_out_dir: Path | None = None
        self._last_report: Path | None = None
        self.settings: UserSettings = load_settings()

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.minsize(740, 560)
        self.root.report_callback_exception = self._report_callback_exception

        self.input_var = tk.StringVar()
        default_preset_info = PRESET_DEFINITIONS.get(
            self.settings.default_preset, PRESET_DEFINITIONS[DEFAULT_PRESET_KEY]
        )
        self.preset_var = tk.StringVar(value=default_preset_info["display_name"])
        self.custom_config_var = tk.StringVar()
        self.out_var = tk.StringVar(value=self.settings.last_output_dir)
        self.deformer_var = tk.StringVar(value=DEFORMERS["idw"][0])
        self.atlas_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready.")

        self.merge_donor_var = tk.StringVar()
        self.merge_outfit_var = tk.StringVar()
        self.merge_out_var = tk.StringVar()
        self.merge_shrink_var = tk.StringVar(value="0.02")
        self.merge_strategy_var = tk.StringVar(value=MERGE_SUBMESH_STRATEGIES[0])
        self._merge_worker: threading.Thread | None = None

        self._build_widgets()
        self._update_preset_ui_state()
        self._init_dnd()
        self.root.after(100, self._drain_events)

    def _init_dnd(self) -> None:
        try:
            import windnd

            def on_drop(files):
                for f in files:
                    if isinstance(f, bytes):
                        f = f.decode("utf-8", errors="replace")
                    p = Path(f)
                    if p.is_dir():
                        self.out_var.set(str(p))
                        self.settings.last_output_dir = str(p)
                        save_settings(self.settings)
                        self._log(f"[Drop] Set output folder: {p}")
                    elif p.suffix.lower() in {".7z", ".zip", ".nif"}:
                        self.input_var.set(str(p))
                        self.settings.last_input_dir = str(p.parent)
                        save_settings(self.settings)
                        self._log(f"[Drop] Set outfit input: {p}")
                    elif p.suffix.lower() == ".json":
                        if "body" in p.name.lower() or "config" in p.name.lower():
                            self.preset_var.set(CUSTOM_CONFIG_LABEL)
                            self.custom_config_var.set(str(p))
                            self._update_preset_ui_state()
                            self.settings.last_config_dir = str(p.parent)
                            save_settings(self.settings)
                            self._log(f"[Drop] Set custom body config: {p}")
                        else:
                            self.input_var.set(str(p))
                            self.settings.last_input_dir = str(p.parent)
                            save_settings(self.settings)
                            self._log(f"[Drop] Set outfit input: {p}")

            windnd.hook_dropfiles(self.root, func=on_drop)
        except Exception:
            pass

    # -- layout ---------------------------------------------------------
    def _build_widgets(self) -> None:
        tk, ttk = self._tk, self._ttk
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        # Row 0: Outfit input
        self._file_row(frame, 0, "Skyrim outfit input:", self.input_var, self._browse_input)

        # Row 1: Body Preset combobox
        ttk.Label(frame, text="Body target preset:").grid(row=1, column=0, sticky="w", pady=4)
        self.preset_combo = ttk.Combobox(
            frame,
            textvariable=self.preset_var,
            values=preset_labels(),
            state="readonly",
        )
        self.preset_combo.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=4)
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_change)

        # Row 2: Custom config JSON (active only if custom is chosen)
        ttk.Label(frame, text="Custom body config:").grid(row=2, column=0, sticky="w", pady=4)
        self.custom_config_entry = ttk.Entry(frame, textvariable=self.custom_config_var)
        self.custom_config_entry.grid(row=2, column=1, sticky="ew", padx=6, pady=4)
        self.custom_config_btn = ttk.Button(frame, text="Browse...", command=self._browse_config)
        self.custom_config_btn.grid(row=2, column=2, sticky="w", pady=4)

        # Row 3: Output folder
        self._file_row(frame, 3, "Output folder:", self.out_var, self._browse_out)

        # Row 4: Deformer
        ttk.Label(frame, text="Deformer:").grid(row=4, column=0, sticky="w", pady=4)
        self.deformer_box = ttk.Combobox(
            frame,
            textvariable=self.deformer_var,
            values=deformer_labels(),
            state="readonly",
            width=44,
        )
        self.deformer_box.grid(row=4, column=1, sticky="w", padx=6, pady=4)
        self.deformer_box.bind("<<ComboboxSelected>>", self._on_deformer_change)

        # Row 5: Atlas option
        self.atlas_check = ttk.Checkbutton(
            frame,
            text="Auto-pack textures into single atlas (Blender-free 1-material donor mode)",
            variable=self.atlas_var,
        )
        self.atlas_check.grid(row=5, column=1, columnspan=2, sticky="w", padx=6, pady=4)

        # Row 6: Action Buttons
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 6))
        self.convert_btn = ttk.Button(buttons, text="Convert", command=self._start_convert)
        self.convert_btn.pack(side="left")
        self.report_btn = ttk.Button(buttons, text="Show report", command=self._show_report, state="disabled")
        self.report_btn.pack(side="left", padx=6)
        self.folder_btn = ttk.Button(buttons, text="Open output folder", command=self._open_output, state="disabled")
        self.folder_btn.pack(side="left")

        # Row 7: Progress bar
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(0, 6))

        # Row 8: Status label
        ttk.Label(frame, textvariable=self.status_var).grid(row=8, column=0, columnspan=3, sticky="w")

        # Row 9: Donor-merge section separator + fields (experimental, no Blender)
        ttk.Separator(frame, orient="horizontal").grid(row=9, column=0, columnspan=3, sticky="ew", pady=(10, 4))
        ttk.Label(frame, text="Donor merge (geometry merge; weights auto-inferred by CrimsonForge on rebuild) --").grid(
            row=10, column=0, columnspan=3, sticky="w"
        )
        self._file_row(frame, 11, "Donor item .obj:", self.merge_donor_var, self._browse_merge_donor)
        self._file_row(frame, 12, "Converted outfit .obj:", self.merge_outfit_var, self._browse_merge_outfit)
        self._file_row(frame, 13, "Merged output .obj:", self.merge_out_var, self._browse_merge_out)

        merge_options = ttk.Frame(frame)
        merge_options.grid(row=14, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(merge_options, text="Shrink factor:").pack(side="left")
        ttk.Entry(merge_options, textvariable=self.merge_shrink_var, width=8).pack(side="left", padx=(4, 12))
        ttk.Label(merge_options, text="Submesh strategy:").pack(side="left")
        self.merge_strategy_box = ttk.Combobox(
            merge_options,
            textvariable=self.merge_strategy_var,
            values=MERGE_SUBMESH_STRATEGIES,
            state="readonly",
            width=10,
        )
        self.merge_strategy_box.pack(side="left", padx=(4, 0))

        merge_buttons = ttk.Frame(frame)
        merge_buttons.grid(row=15, column=0, columnspan=3, sticky="w", pady=(4, 6))
        self.merge_btn = ttk.Button(merge_buttons, text="Merge (experimental)", command=self._start_merge)
        self.merge_btn.pack(side="left")

        # Row 16: Log area
        log_frame = ttk.Frame(frame)
        log_frame.grid(row=16, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        frame.rowconfigure(16, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        self._log(
            "sky2cd GUI ready.\n"
            "Built-in body presets: Fem Kliff (Default) & CD Vanilla Female.\n"
            "PAC output is experimental and unverified against real Crimson Desert files.\n"
            ".nif input requires your own PyNifly installation on PYTHONPATH.\n"
            "Donor merge produces geometry only, but VERIFIED against the real game "
            "(v2.02.00) + CrimsonForge v1.26.0 source: CrimsonForge's build_pac() "
            "auto-infers bone weights for new vertices from the nearest ORIGINAL donor "
            "vertex on rebuild -- no .cfmeta.json sidecar or Blender weight-painting is "
            "required for the mechanism to work. Coverage depends on how densely the "
            "donor itself is weighted -- see README.md.\n"
        )

    def _file_row(self, parent, row: int, label: str, var, command) -> None:
        ttk = self._ttk
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(parent, text="Browse...", command=command).grid(row=row, column=2, sticky="w", pady=4)

    def _update_preset_ui_state(self) -> None:
        is_custom = self.preset_var.get() == CUSTOM_CONFIG_LABEL
        if is_custom:
            self.custom_config_entry.configure(state="normal")
            self.custom_config_btn.configure(state="normal")
        else:
            self.custom_config_entry.configure(state="disabled")
            self.custom_config_btn.configure(state="disabled")

    # -- actions --------------------------------------------------------
    def _on_preset_change(self, _event=None) -> None:
        self._update_preset_ui_state()
        selected = self.preset_var.get()
        if is_preset_key(selected):
            key = normalize_preset_key(selected)
            self.settings.default_preset = key
            save_settings(self.settings)

    def _browse_input(self) -> None:
        from tkinter import filedialog

        init_dir = self.settings.last_input_dir
        if not init_dir and self.input_var.get():
            try:
                init_dir = str(Path(self.input_var.get()).parent)
            except Exception:
                init_dir = ""

        path = filedialog.askopenfilename(
            title="Select Skyrim outfit or mod archive",
            initialdir=init_dir or None,
            filetypes=[
                ("Outfit meshes and mod archives", "*.nif *.json *.7z *.zip"),
                ("Mod archives (.7z, .zip)", "*.7z *.zip"),
                ("Skyrim NIF (*.nif)", "*.nif"),
                ("MeshIR JSON (*.json)", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.input_var.set(path)
            self.settings.last_input_dir = str(Path(path).parent)
            save_settings(self.settings)

    def _browse_config(self) -> None:
        from tkinter import filedialog

        init_dir = (
            self.settings.last_config_dir
            or (str(Path(self.input_var.get()).parent) if self.input_var.get() else "")
            or self.settings.last_input_dir
        )

        path = filedialog.askopenfilename(
            title="Select custom body config JSON",
            initialdir=init_dir or None,
            filetypes=[("Body config JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.preset_var.set(CUSTOM_CONFIG_LABEL)
            self.custom_config_var.set(path)
            self._update_preset_ui_state()
            self.settings.last_config_dir = str(Path(path).parent)
            save_settings(self.settings)

    def _browse_out(self) -> None:
        from tkinter import filedialog

        init_dir = (
            self.settings.last_output_dir
            or (str(Path(self.input_var.get()).parent) if self.input_var.get() else "")
            or self.settings.last_input_dir
        )

        path = filedialog.askdirectory(title="Select output folder", initialdir=init_dir or None)
        if path:
            self.out_var.set(path)
            self.settings.last_output_dir = str(Path(path))
            save_settings(self.settings)

    def _on_deformer_change(self, _event=None) -> None:
        name = label_to_deformer(self.deformer_var.get())
        if not deformer_is_available(name):
            self._log(f"'{name}' is a stub deformer and cannot run. Falling back to idw.")
            self.deformer_var.set(DEFORMERS["idw"][0])

    def _browse_merge_donor(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="Select donor item .obj (e.g. exported from CrimsonForge)",
            filetypes=[("Wavefront OBJ", "*.obj"), ("All files", "*.*")],
        )
        if path:
            self.merge_donor_var.set(path)

    def _browse_merge_outfit(self) -> None:
        from tkinter import filedialog

        init_dir = self.settings.last_output_dir
        path = filedialog.askopenfilename(
            title="Select converted outfit .obj",
            initialdir=init_dir or None,
            filetypes=[("Wavefront OBJ", "*.obj"), ("All files", "*.*")],
        )
        if path:
            self.merge_outfit_var.set(path)

    def _browse_merge_out(self) -> None:
        from tkinter import filedialog

        init_dir = self.settings.last_output_dir
        path = filedialog.asksaveasfilename(
            title="Save merged .obj as",
            initialdir=init_dir or None,
            defaultextension=".obj",
            filetypes=[("Wavefront OBJ", "*.obj"), ("All files", "*.*")],
        )
        if path:
            self.merge_out_var.set(path)

    def _get_active_body_config(self) -> str:
        preset_selection = self.preset_var.get()
        if preset_selection == CUSTOM_CONFIG_LABEL:
            return self.custom_config_var.get()
        return preset_selection

    def _start_convert(self) -> None:
        from tkinter import messagebox

        try:
            request = validate_inputs(
                self.input_var.get(),
                self._get_active_body_config(),
                self.out_var.get(),
                label_to_deformer(self.deformer_var.get()),
                atlas=self.atlas_var.get(),
            )
        except ValidationError as exc:
            self._log(f"ERROR: {exc}")
            self.status_var.set("Fix the highlighted problem and try again.")
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self.convert_btn.configure(state="disabled")
        self.report_btn.configure(state="disabled")
        self.folder_btn.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Converting...")
        self._log(
            f"Converting {request.input_path}\n"
            f"  body target : {request.body_config}\n"
            f"  output      : {request.out_dir}\n"
            f"  deformer    : {request.deformer}\n"
            f"  atlas       : {request.atlas}"
        )
        self._worker = threading.Thread(target=self._convert_worker, args=(request,), daemon=True)
        self._worker.start()

    def _start_merge(self) -> None:
        from tkinter import messagebox

        try:
            request = validate_merge_inputs(
                self.merge_donor_var.get(),
                self.merge_outfit_var.get(),
                self.merge_out_var.get(),
                self.merge_shrink_var.get(),
                self.merge_strategy_var.get(),
            )
        except ValidationError as exc:
            self._log(f"ERROR: {exc}")
            self.status_var.set("Fix the highlighted problem and try again.")
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self.merge_btn.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Merging (experimental)...")
        self._log(
            f"Merging (EXPERIMENTAL, unverified):\n"
            f"  donor    : {request.donor_path}\n"
            f"  outfit   : {request.outfit_path}\n"
            f"  out      : {request.out_path}\n"
            f"  shrink   : {request.shrink_factor}\n"
            f"  strategy : {request.submesh_strategy}"
        )
        self._merge_worker = threading.Thread(target=self._merge_worker_run, args=(request,), daemon=True)
        self._merge_worker.start()

    def _report_callback_exception(self, exc_type, exc_value, exc_tb) -> None:
        """Tk swallows exceptions raised inside widget callbacks by default.

        Without a console window (this is a --windowed exe) that means the
        error simply vanishes. Log it to disk and surface it to the user
        instead so a callback bug shows up as a dialog, not a silent exit.
        """
        from tkinter import messagebox

        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write_crash_log("tk callback exception", detail)
        message = f"{exc_type.__name__}: {exc_value}"
        self._log(f"ERROR (internal): {message}\n{detail}")
        try:
            messagebox.showerror(APP_TITLE, f"Internal error:\n{message}\n\nDetails written to {crash_log_path()}")
        except Exception:
            pass  # avoid a second callback exception while reporting the first

    def _convert_worker(self, request: ConvertRequest) -> None:
        from sky2cd.pipeline import convert

        try:
            result = convert(
                request.input_path,
                request.body_config,
                request.out_dir,
                request.deformer,
                atlas=request.atlas,
            )
        except Exception as exc:  # surfaced verbatim; never silently swallowed
            self._events.put(("error", f"{type(exc).__name__}: {exc}", traceback.format_exc()))
        else:
            self._events.put(("done", result, request))

    def _merge_worker_run(self, request: MergeRequest) -> None:
        try:
            from sky2cd.donor_merge import merge_onto_donor
            from sky2cd.exporters.obj_exporter import write_obj
            from sky2cd.importers.obj_importer import read_obj

            donor = read_obj(request.donor_path)
            outfit = read_obj(request.outfit_path)
            merged = merge_onto_donor(
                donor,
                outfit,
                shrink_factor=request.shrink_factor,
                submesh_strategy=request.submesh_strategy,
            )
            out_path = write_obj(merged, request.out_path, axis_convert=False)
        except Exception as exc:  # surfaced verbatim; never silently swallowed
            self._events.put(("merge_error", f"{type(exc).__name__}: {exc}", traceback.format_exc()))
        else:
            self._events.put(("merge_done", out_path, request))

    def _drain_events(self) -> None:
        try:
            while True:
                event = self._events.get_nowait()
                if event[0] == "done":
                    self._on_success(event[1], event[2])
                elif event[0] == "error":
                    self._on_failure(event[1], event[2])
                elif event[0] == "merge_done":
                    self._on_merge_success(event[1], event[2])
                elif event[0] == "merge_error":
                    self._on_merge_failure(event[1], event[2])
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _on_success(self, result, request: ConvertRequest) -> None:
        from sky2cd.pipeline import pretty_report

        self.progress.stop()
        self.convert_btn.configure(state="normal")
        self._last_out_dir = request.out_dir
        self._last_report = Path(result.report_path)
        self.report_btn.configure(state="normal")
        self.folder_btn.configure(state="normal")
        self.status_var.set(
            "Geometry preview only - NOT body fitted."
            if result.report.get("geometry_mode") == "rigid_preview" else "Experimental body fit finished."
        )
        obj_path = result.report.get("output_obj") or (result.report.get("mesh") or {}).get("obj_path")
        self._log(
            f"Wrote {obj_path} (usable output -- feed this to CrimsonForge, see README)\n"
            f"Wrote {result.pac_path} (legacy, not game-loadable)\n"
            f"Wrote {result.report_path}\n"
        )
        self._log(pretty_report(result.report_path) + "\n")

    def _on_failure(self, message: str, detail: str) -> None:
        from tkinter import messagebox

        self.progress.stop()
        self.convert_btn.configure(state="normal")
        self.status_var.set("Conversion failed.")
        self._log(f"ERROR: {message}\n{detail}")
        _write_crash_log("conversion failed", detail)
        messagebox.showerror(APP_TITLE, f"{message}\n\nDetails written to {crash_log_path()}")

    def _on_merge_success(self, out_path: Path, request: MergeRequest) -> None:
        self.progress.stop()
        self.merge_btn.configure(state="normal")
        self.status_var.set("Merge finished (see log for weight-inference details).")
        self._log(
            f"Wrote {out_path}\n"
            "VERIFIED against the real game (v2.02.00) + CrimsonForge v1.26.0 source: "
            "when you import this .obj back over the donor's ORIGINAL exported .obj "
            "(same file, same source_path/source_format header) and rebuild with "
            "CrimsonForge's build_pac(), new vertices automatically inherit bone "
            "weights from the nearest original donor vertex -- no .cfmeta.json sidecar "
            "or Blender weight-painting is required for this to work mechanically. "
            "Coverage still depends on the donor's own weight density (some donor "
            "vertices are themselves unweighted/rigid, so new geometry landing there "
            "also stays unweighted). See README.md for the full explanation.\n"
        )

    def _on_merge_failure(self, message: str, detail: str) -> None:
        from tkinter import messagebox

        self.progress.stop()
        self.merge_btn.configure(state="normal")
        self.status_var.set("Merge failed.")
        self._log(f"ERROR: {message}\n{detail}")
        _write_crash_log("merge failed", detail)
        messagebox.showerror(APP_TITLE, f"{message}\n\nDetails written to {crash_log_path()}")

    def _show_report(self) -> None:
        from sky2cd.pipeline import pretty_report
        from tkinter import messagebox

        if self._last_report is None:
            return
        try:
            self._log(pretty_report(self._last_report) + "\n")
        except (OSError, ValueError) as exc:
            self._log(f"ERROR: {exc}")
            messagebox.showerror(APP_TITLE, str(exc))

    def _open_output(self) -> None:
        from tkinter import messagebox

        if self._last_out_dir is None:
            return
        try:
            open_folder(self._last_out_dir)
        except (ValidationError, OSError) as exc:
            self._log(f"ERROR: {exc}")
            messagebox.showerror(APP_TITLE, str(exc))

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def mainloop(self) -> None:
        self.root.mainloop()


def main() -> int:
    return run()


if __name__ == "__main__":
    # Defensive, same real reason as sky2cd.cli's __main__ guard: this file
    # is PyInstaller's direct entry script for sky2cd-gui.exe, so it runs as
    # __main__ there too. If the GUI ever drives a multi-piece batch
    # conversion with `max_workers` (auto_replace.auto_replace_batch_from_skyrim's
    # ProcessPoolExecutor path), the frozen exe needs this call, in this
    # exact spot, before anything else -- otherwise each spawned child would
    # re-run the whole GUI instead of just its worker function.
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
