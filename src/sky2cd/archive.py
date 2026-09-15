"""Archive extraction and mesh discovery helpers for .7z and .zip mod packages."""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

ARCHIVE_EXTENSIONS = {".7z", ".zip"}


def is_archive(path: str | Path) -> bool:
    """Return True if path has an archive extension (.7z, .zip)."""
    return Path(path).suffix.lower() in ARCHIVE_EXTENSIONS


def extract_archive(archive_path: str | Path, dest_dir: str | Path) -> list[Path]:
    """Extract a .zip or .7z archive into dest_dir.

    Returns a list of extracted file Paths.
    """
    archive_path = Path(archive_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    suffix = archive_path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
    elif suffix == ".7z":
        try:
            import py7zr
        except ImportError as exc:
            raise ImportError(
                "py7zr is required to extract .7z archives. Install it with: pip install py7zr"
            ) from exc
        with py7zr.SevenZipFile(archive_path, mode="r") as sz:
            sz.extractall(path=dest_dir)
    else:
        raise ValueError(f"Unsupported archive format: {archive_path.suffix}")

    extracted_files: list[Path] = []
    for root, _, files in os.walk(dest_dir):
        for f in files:
            extracted_files.append(Path(root) / f)
    return extracted_files


def discover_meshes(directory: str | Path, prefer_high_weight: bool = True) -> list[Path]:
    """Scan directory recursively for .nif and .meshir.json files.

    If prefer_high_weight is True and both `name_0.nif` and `name_1.nif` exist in
    the same directory, only `name_1.nif` is selected (standard Skyrim max-weight).

    Two categories of real Skyrim mod files are excluded because they are not the
    equipped, in-game outfit mesh and would otherwise be double-converted as if
    they were separate armor pieces:

      * ``CalienteTools/BodySlide/...`` — BodySlide's own project/reference-shape
        copies (used only to build sliders in BodySlide itself, never loaded by
        the game as worn equipment).
      * a path component named ``GND`` (case-insensitive) — Skyrim's convention
        for the low-detail "on the ground" pickup mesh, distinct from the
        higher-detail worn mesh with the same base name.
    """
    directory = Path(directory)
    all_nifs: list[Path] = []
    all_json_meshes: list[Path] = []

    for root, _, files in os.walk(directory):
        if _is_excluded_dir(Path(root), directory):
            continue
        for f in files:
            p = Path(root) / f
            low = f.lower()
            if low.endswith(".nif"):
                all_nifs.append(p)
            elif low.endswith(".meshir.json"):
                all_json_meshes.append(p)
            elif low.endswith(".json") and not low.endswith("report.json") and not low.endswith("config.json") and not low.endswith("mappings.json"):
                # Potential standalone MeshIR JSON
                all_json_meshes.append(p)

    selected: list[Path] = []

    if prefer_high_weight:
        # Group NIFs by directory and base name (stripping _0 / _1)
        # E.g. cuirass_0.nif and cuirass_1.nif -> keep cuirass_1.nif
        by_pair: dict[tuple[Path, str], list[Path]] = {}
        for nif in all_nifs:
            stem = nif.stem
            if stem.endswith("_0") or stem.endswith("_1"):
                base_stem = stem[:-2]
                key = (nif.parent, base_stem.lower())
                by_pair.setdefault(key, []).append(nif)
            else:
                selected.append(nif)

        for _, variants in by_pair.items():
            # If _1 exists, prefer it, otherwise take whatever is present
            v1 = [v for v in variants if v.stem.endswith("_1")]
            if v1:
                selected.extend(v1)
            else:
                selected.extend(variants)
    else:
        selected.extend(all_nifs)

    selected.extend(all_json_meshes)
    # Sort for deterministic processing order
    selected.sort(key=lambda p: str(p).lower())
    return selected


def _is_excluded_dir(candidate: Path, root: Path) -> bool:
    """Return True if candidate is (or is under) a directory discover_meshes skips."""
    try:
        rel_parts = candidate.relative_to(root).parts
    except ValueError:
        rel_parts = candidate.parts
    lowered = [part.lower() for part in rel_parts]
    if "calientetools" in lowered:
        return True
    if "gnd" in lowered:
        return True
    return False
