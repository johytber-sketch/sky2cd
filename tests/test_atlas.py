import numpy as np
from pathlib import Path
from PIL import Image
import pytest

from sky2cd.meshir import MeshIR, save_meshir
from sky2cd.pipeline import convert
from sky2cd.textures.atlas import compute_atlas_plan, repack_uvs_to_atlas
from sky2cd.textures.compositor import composite_texture_atlas


def test_atlas_plan_computation_grid_layout():
    # 4 submeshes -> 2x2 grid
    materials = [
        {"shape": "dress", "textures": {"diffuse": "dress.dds", "normal": "dress_n.dds"}},
        {"shape": "belt", "textures": {"diffuse": "belt.dds", "normal": "belt_n.dds"}},
        {"shape": "panties", "textures": {"diffuse": "panties.dds", "normal": "panties_n.dds"}},
        {"shape": "boots", "textures": {"diffuse": "boots.dds", "normal": "boots_n.dds"}},
    ]
    mesh = MeshIR(
        positions=np.zeros((8, 3), dtype=np.float32),
        normals=np.zeros((8, 3), dtype=np.float32),
        uvs=np.array([[0.0, 0.0], [1.0, 1.0]] * 4, dtype=np.float32),
        triangles=np.array([[0, 1, 2], [2, 3, 4], [4, 5, 6], [6, 7, 0]], dtype=np.uint32),
        submesh_ids=np.array([0, 1, 2, 3], dtype=np.int32),
        materials=materials,
        name="test_outfit",
    )

    plan = compute_atlas_plan(mesh)
    assert plan.cols == 2
    assert plan.rows == 2
    assert len(plan.cells) == 4
    assert plan.cells[0].material_name == "dress"
    assert plan.cells[1].material_name == "belt"


def test_repack_uvs_to_atlas_scales_and_offsets_correctly():
    # Submesh 0 (col=0, row_from_top=0 -> row=1 in UV space)
    # Submesh 1 (col=1, row_from_top=0 -> row=1 in UV space)
    materials = [
        {"shape": "dress", "textures": {"diffuse": "dress.png"}},
        {"shape": "belt", "textures": {"diffuse": "belt.png"}},
    ]
    # 2 disjoint triangles
    mesh = MeshIR(
        positions=np.array([
            [0, 0, 0], [1, 0, 0], [0, 1, 0],
            [10, 0, 0], [11, 0, 0], [10, 1, 0],
        ], dtype=np.float32),
        normals=np.zeros((6, 3), dtype=np.float32),
        uvs=np.array([
            [0.0, 0.0], [1.0, 0.0], [0.5, 1.0],  # Submesh 0 UVs in [0, 1]
            [0.0, 0.0], [1.0, 0.0], [0.5, 1.0],  # Submesh 1 UVs in [0, 1]
        ], dtype=np.float32),
        triangles=np.array([[0, 1, 2], [3, 4, 5]], dtype=np.uint32),
        submesh_ids=np.array([0, 1], dtype=np.int32),
        materials=materials,
        name="dress_and_belt",
    )

    repacked, plan = repack_uvs_to_atlas(mesh)
    assert repacked.submesh_ids is None
    assert len(repacked.materials) == 1

    # In a 2-item atlas (grid 2x1 or 2x2):
    # Submesh 0 should be in left column (u in [0, 0.5])
    # Submesh 1 should be in right column (u in [0.5, 1.0])
    sub0_uvs = repacked.uvs[:3]
    sub1_uvs = repacked.uvs[3:]

    assert np.all(sub0_uvs[:, 0] <= 0.5 + 1e-5)
    assert np.all(sub1_uvs[:, 0] >= 0.5 - 1e-5)


def test_composite_texture_atlas_creates_composite_images(tmp_path):
    # Create 2 small test textures
    img1 = Image.new("RGBA", (128, 128), (255, 0, 0, 255))  # Red
    img2 = Image.new("RGBA", (128, 128), (0, 255, 0, 255))  # Green
    img1_path = tmp_path / "red.png"
    img2_path = tmp_path / "green.png"
    img1.save(img1_path)
    img2.save(img2_path)

    materials = [
        {"shape": "part1", "textures": {"diffuse": "red.png", "normal": "none.dds"}},
        {"shape": "part2", "textures": {"diffuse": "green.png", "normal": "none.dds"}},
    ]
    mesh = MeshIR(
        positions=np.zeros((6, 3), dtype=np.float32),
        normals=np.zeros((6, 3), dtype=np.float32),
        uvs=np.zeros((6, 2), dtype=np.float32),
        triangles=np.array([[0, 1, 2], [3, 4, 5]], dtype=np.uint32),
        submesh_ids=np.array([0, 1], dtype=np.int32),
        materials=materials,
        name="composite_test",
    )

    _, plan = repack_uvs_to_atlas(mesh)
    diff_path, _ = composite_texture_atlas(
        plan, tmp_path / "out_atlas", search_dirs=[tmp_path], atlas_resolution=512
    )

    assert diff_path is not None
    assert diff_path.is_file()
    result_img = Image.open(diff_path)
    assert result_img.size == (512, 512)
    # Check top-left pixel is Red and top-right is Green
    px_top_left = result_img.getpixel((10, 10))
    px_top_right = result_img.getpixel((500, 10))
    assert px_top_left[0] > 200  # Red channel
    assert px_top_right[1] > 200  # Green channel


def test_pipeline_convert_with_atlas_flag(tmp_path):
    tex_dir = tmp_path / "textures"
    tex_dir.mkdir()
    tex1 = Image.new("RGBA", (64, 64), (100, 150, 200, 255))
    tex1.save(tex_dir / "dress_d.png")

    mesh = MeshIR(
        positions=np.array([
            [0, 0, 100], [1, 0, 100], [0, 1, 100],
            [2, 0, 100], [3, 0, 100], [2, 1, 100],
        ], dtype=np.float32),
        normals=np.array([[0, 1, 0]] * 6, dtype=np.float32),
        uvs=np.array([[0, 0], [1, 0], [0, 1], [0, 0], [1, 0], [0, 1]], dtype=np.float32),
        triangles=np.array([[0, 1, 2], [3, 4, 5]], dtype=np.uint32),
        submesh_ids=np.array([0, 1], dtype=np.int32),
        materials=[
            {"shape": "dress", "textures": {"diffuse": "dress_d.png"}},
            {"shape": "belt", "textures": {"diffuse": "dress_d.png"}},
        ],
        name="multi_part_outfit",
    )
    mesh_path = save_meshir(mesh, tmp_path / "multi_part.meshir.json")
    out_dir = tmp_path / "atlas_out"

    result = convert(mesh_path, "fem_kliff", out_dir, atlas=True)
    assert result.pac_path.is_file()
    assert (out_dir / "multi_part.obj").is_file()
    assert (out_dir / "multi_part_atlas_diffuse.png").is_file()
