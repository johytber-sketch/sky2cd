"""Texture atlas compositor: merges diffuse and normal maps into unified master textures."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from PIL import Image

from sky2cd.textures.atlas import AtlasPlan

logger = logging.getLogger(__name__)

# Standard neutral normal map color (RGB 128, 128, 255) for flat tangent-space normals
NEUTRAL_NORMAL_COLOR = (128, 128, 255, 255)
DEFAULT_DIFFUSE_BG = (40, 40, 40, 255)


def composite_texture_atlas(
    plan: AtlasPlan,
    out_dir: str | Path,
    search_dirs: Sequence[str | Path] = (),
    *,
    atlas_resolution: int = 4096,
) -> tuple[Path | None, Path | None]:
    """Composite individual submesh textures into unified diffuse and normal atlas images.

    Returns ``(diffuse_atlas_path, normal_atlas_path)``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if plan.is_identity:
        return None, None

    cols = max(1, plan.cols)
    rows = max(1, plan.rows)
    cell_w = atlas_resolution // cols
    cell_h = atlas_resolution // rows

    diffuse_canvas = Image.new("RGBA", (atlas_resolution, atlas_resolution), DEFAULT_DIFFUSE_BG)
    normal_canvas = Image.new("RGBA", (atlas_resolution, atlas_resolution), NEUTRAL_NORMAL_COLOR)

    has_diffuse = False
    has_normal = False

    search_paths = [Path(p) for p in search_dirs]

    for cell in plan.cells:
        # Image pixel coordinates: Y=0 is top, so row_from_top is (rows - 1 - cell.row)
        row_from_top = (rows - 1) - cell.row
        box_x = cell.col * cell_w
        box_y = row_from_top * cell_h
        target_box = (box_x, box_y, box_x + cell_w, box_y + cell_h)

        # 1. Composite Diffuse
        if cell.diffuse_path:
            diff_img = _find_and_open_image(cell.diffuse_path, search_paths)
            if diff_img is not None:
                has_diffuse = True
                resized = diff_img.resize((cell_w, cell_h), Image.Resampling.LANCZOS)
                diffuse_canvas.paste(resized, (box_x, box_y))

        # 2. Composite Normal Map
        if cell.normal_path:
            norm_img = _find_and_open_image(cell.normal_path, search_paths)
            if norm_img is not None:
                has_normal = True
                resized_norm = norm_img.resize((cell_w, cell_h), Image.Resampling.LANCZOS)
                normal_canvas.paste(resized_norm, (box_x, box_y))

    diffuse_path: Path | None = None
    normal_path: Path | None = None

    if has_diffuse:
        diffuse_path = out_dir / f"{plan.atlas_name}_diffuse.png"
        diffuse_canvas.save(diffuse_path, format="PNG")

    if has_normal:
        normal_path = out_dir / f"{plan.atlas_name}_normal.png"
        normal_canvas.save(normal_path, format="PNG")

    return diffuse_path, normal_path


def _find_and_open_image(rel_or_abs_path: str | Path, search_paths: Sequence[Path]) -> Image.Image | None:
    """Find and open an image file from explicit path or relative to search directories."""
    candidate_paths: list[Path] = []
    raw = Path(rel_or_abs_path)
    if raw.is_file():
        candidate_paths.append(raw)

    filename = raw.name
    # Direct search in search paths
    for s_dir in search_paths:
        candidate_paths.append(s_dir / raw)
        candidate_paths.append(s_dir / filename)
        candidate_paths.append(s_dir / "textures" / raw)
        candidate_paths.append(s_dir / "textures" / filename)
        # Search recursively for exact filename match
        try:
            for match in s_dir.rglob(filename):
                if match.is_file():
                    candidate_paths.append(match)
        except Exception:
            pass

    for cand in candidate_paths:
        if cand.is_file():
            try:
                img = Image.open(cand)
                return img.convert("RGBA")
            except Exception as exc:
                logger.debug("Failed to open image %s: %s", cand, exc)

    return None
