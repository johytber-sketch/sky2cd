from __future__ import annotations

from pathlib import Path
import warnings

import numpy as np

from sky2cd.meshir import MeshIR


def import_nif(path: str | Path, *, exclude_shapes: tuple[str, ...] = ()) -> MeshIR:
    """Import a Skyrim `.nif` file into MeshIR using optional pynifly support.

    Real NIF parsing depends on the external `pynifly` package and actual Skyrim
    assets. The optional boundary is explicit so tests and non-NIF workflows do
    not require Blender, game files, or importer-specific native dependencies.
    """

    pynifly = _load_pynifly_module()

    nif_path = Path(path)
    if not nif_path.exists():
        raise FileNotFoundError(nif_path)

    try:
        nif = pynifly.NifFile(str(nif_path))
    except (OSError, FileNotFoundError) as exc:
        raise ImportError(
            "PyNifly is installed but its native NiflyDLL could not be loaded. "
            "Install the Windows PyNifly GitHub release add-on and ensure its "
            "io_scene_nifly directory is on PYTHONPATH."
        ) from exc

    return _meshir_from_pynifly_nif(nif, nif_path.stem, exclude_shapes=exclude_shapes)


def _load_pynifly_module():
    import sys

    # First check if pynifly or pyn is already imported/monkeypatched
    if "pynifly" in sys.modules:
        m = sys.modules["pynifly"]
        if hasattr(m, "NifFile"):
            return m
        if hasattr(m, "pynifly") and hasattr(m.pynifly, "NifFile"):
            return m.pynifly
    if "pyn" in sys.modules:
        m = sys.modules["pyn"]
        if hasattr(m, "pynifly") and hasattr(m.pynifly, "NifFile"):
            return m.pynifly

    # 1. Try adding vendored io_scene_nifly directory to sys.path if present
    vendor_nifly_dir = Path(__file__).resolve().parent.parent / "vendor" / "io_scene_nifly"
    if vendor_nifly_dir.is_dir() and str(vendor_nifly_dir) not in sys.path:
        sys.path.insert(0, str(vendor_nifly_dir))

    # Also check PyInstaller frozen sys._MEIPASS
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass_nifly = Path(sys._MEIPASS) / "sky2cd" / "vendor" / "io_scene_nifly"
        if meipass_nifly.is_dir() and str(meipass_nifly) not in sys.path:
            sys.path.insert(0, str(meipass_nifly))

    try:
        from pyn import pynifly  # type: ignore[import-not-found]

        return pynifly
    except (ImportError, OSError, FileNotFoundError):
        pass

    try:
        import pynifly  # type: ignore[import-not-found]

        return pynifly
    except (OSError, FileNotFoundError) as exc:
        raise ImportError(
            "PyNifly was found, but its native NiflyDLL could not be loaded."
        ) from exc
    except ImportError as exc:
        raise ImportError(
            "NIF import requires PyNifly, which is not published as a PyPI wheel. "
            "Download io_scene_nifly.zip from https://github.com/BadDogSkyrim/PyNifly/releases "
            "and put its io_scene_nifly directory on PYTHONPATH so 'from pyn import pynifly' works."
        ) from exc


def _meshir_from_pynifly_nif(nif, mesh_name: str, *, exclude_shapes: tuple[str, ...] = ()) -> MeshIR:
    shapes = list(getattr(nif, "shapes", []))
    if not shapes:
        raise ValueError("NIF file contains no mesh shapes")

    bone_names: list[str] = []
    bone_lookup: dict[str, int] = {}
    positions_parts: list[np.ndarray] = []
    normals_parts: list[np.ndarray] = []
    uvs_parts: list[np.ndarray] = []
    triangle_parts: list[np.ndarray] = []
    submesh_id_parts: list[np.ndarray] = []
    packed_indices_parts: list[np.ndarray] = []
    packed_weights_parts: list[np.ndarray] = []
    materials: list[dict[str, object]] = []
    vertex_offset = 0

    for shape in shapes:
        shape_name = str(getattr(shape, "name", "") or "")
        if shape_name in exclude_shapes:
            warnings.warn(f"Explicitly excluding NIF shape {shape_name!r}.", UserWarning, stacklevel=2)
            continue
        if shape_name.lower().startswith("virtual"):
            warnings.warn(
                f"Retaining possible helper {shape_name!r}; its name alone does not prove "
                "it is non-rendering. Inspect it, then use exclude_shapes for exact exclusions.",
                UserWarning, stacklevel=2,
            )

        positions = _as_float_array(getattr(shape, "verts", []), 3, "verts")
        vertex_count = positions.shape[0]
        if vertex_count == 0:
            continue

        normals = _optional_float_array(getattr(shape, "normals", []), vertex_count, 3)
        uvs = _optional_float_array(getattr(shape, "uvs", []), vertex_count, 2)
        triangles = _as_uint_array(getattr(shape, "tris", []), 3, "tris")

        _, shape_indices, shape_weights = _pack_shape_weights(
            getattr(shape, "bone_weights", {}),
            vertex_count,
            bone_lookup,
            bone_names,
        )

        positions_parts.append(positions)
        normals_parts.append(normals)
        uvs_parts.append(uvs)
        triangle_parts.append(triangles + vertex_offset)
        submesh_id_parts.append(np.full(triangles.shape[0], len(materials), dtype=np.int32))
        packed_indices_parts.append(shape_indices)
        packed_weights_parts.append(shape_weights)
        materials.append(_shape_material(shape))
        vertex_offset += vertex_count

    if not positions_parts:
        raise ValueError("NIF file contains shapes, but none have vertices")

    # A single-shape NIF is the common case and matches MeshIR's "None means
    # one implicit submesh" convention; only carry explicit per-triangle ids
    # when there is more than one shape/submesh to distinguish.
    submesh_ids = (
        np.concatenate(submesh_id_parts, axis=0) if len(materials) > 1 else None
    )

    return MeshIR(
        positions=np.concatenate(positions_parts, axis=0),
        normals=np.concatenate(normals_parts, axis=0),
        uvs=np.concatenate(uvs_parts, axis=0),
        triangles=np.concatenate(triangle_parts, axis=0) if triangle_parts else np.zeros((0, 3), dtype=np.uint32),
        bone_names=bone_names,
        bone_indices=np.concatenate(packed_indices_parts, axis=0),
        bone_weights=np.concatenate(packed_weights_parts, axis=0),
        materials=materials,
        name=mesh_name,
        submesh_ids=submesh_ids,
    )


def _pack_shape_weights(
    weights_by_bone: dict[str, list[tuple[int, float]]],
    vertex_count: int,
    bone_lookup: dict[str, int],
    bone_names: list[str],
) -> tuple[list[str], np.ndarray, np.ndarray]:
    influences: list[list[tuple[int, float]]] = [[] for _ in range(vertex_count)]
    for bone_name, weights in weights_by_bone.items():
        if bone_name not in bone_lookup:
            bone_lookup[bone_name] = len(bone_names)
            bone_names.append(bone_name)
        bone_index = bone_lookup[bone_name]
        for vertex_index, weight in weights:
            if 0 <= int(vertex_index) < vertex_count and float(weight) > 0:
                influences[int(vertex_index)].append((bone_index, float(weight)))

    out_indices = np.zeros((vertex_count, 4), dtype=np.uint16)
    out_weights = np.zeros((vertex_count, 4), dtype=np.float32)
    for vertex_index, vertex_influences in enumerate(influences):
        top = sorted(vertex_influences, key=lambda item: item[1], reverse=True)[:4]
        total = sum(weight for _, weight in top)
        if total <= 0:
            continue
        for slot, (bone_index, weight) in enumerate(top):
            out_indices[vertex_index, slot] = np.uint16(bone_index)
            out_weights[vertex_index, slot] = np.float32(weight / total)
    return bone_names, out_indices, out_weights


def _as_float_array(values, width: int, label: str) -> np.ndarray:
    arr = np.asarray(list(values), dtype=np.float32)
    if arr.size == 0:
        return np.zeros((0, width), dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != width:
        raise ValueError(f"PyNifly shape {label} must have shape (n, {width})")
    return arr


def _optional_float_array(values, vertex_count: int, width: int) -> np.ndarray:
    if values is None:
        return np.zeros((vertex_count, width), dtype=np.float32)
    arr = np.asarray(list(values), dtype=np.float32)
    if arr.size == 0:
        return np.zeros((vertex_count, width), dtype=np.float32)
    if arr.ndim != 2 or arr.shape != (vertex_count, width):
        return np.zeros((vertex_count, width), dtype=np.float32)
    return arr


def _as_uint_array(values, width: int, label: str) -> np.ndarray:
    arr = np.asarray(list(values), dtype=np.uint32)
    if arr.size == 0:
        return np.zeros((0, width), dtype=np.uint32)
    if arr.ndim != 2 or arr.shape[1] != width:
        raise ValueError(f"PyNifly shape {label} must have shape (n, {width})")
    return arr


def _shape_material(shape) -> dict[str, object]:
    shader = getattr(shape, "shader", None)
    textures_raw = getattr(shape, "textures", None)
    textures = dict(textures_raw) if isinstance(textures_raw, dict) else {}
    return {
        "shape": getattr(shape, "name", "shape"),
        "shader": getattr(shader, "blockname", None) if shader is not None else None,
        "textures": textures,
        # Convenience aliases so exporters (e.g. OBJ/MTL) don't need to know
        # PyNifly's exact texture-slot naming ("Diffuse"/"Normal") -- these
        # are None when the shape has no such texture assigned.
        "diffuse_texture": _find_texture(textures, "diffuse"),
        "normal_texture": _find_texture(textures, "normal"),
    }


def _find_texture(textures: dict[str, object], keyword: str) -> str | None:
    """Case-insensitively find a texture path whose slot name contains ``keyword``."""
    for slot, path in textures.items():
        if keyword in str(slot).lower() and path:
            return str(path)
    return None
