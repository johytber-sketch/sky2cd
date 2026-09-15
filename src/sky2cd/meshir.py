from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class MeshIR:
    """Game-agnostic mesh intermediate representation."""

    positions: np.ndarray
    normals: np.ndarray | None = None
    uvs: np.ndarray | None = None
    triangles: np.ndarray | None = None
    bone_names: list[str] = field(default_factory=list)
    bone_indices: np.ndarray | None = None
    bone_weights: np.ndarray | None = None
    materials: list[dict[str, Any]] = field(default_factory=list)
    name: str = "mesh"
    submesh_ids: np.ndarray | None = None
    """Optional per-triangle submesh/material group id (shape (n_triangles,), int32).

    ``None`` means "single implicit submesh" -- the default for every existing
    mesh source (NIF import, synthetic test meshes, etc.). Only set when a
    mesh actually has multiple submeshes/materials worth tracking separately,
    e.g. an OBJ imported via :func:`sky2cd.importers.obj_importer.read_obj`
    from a donor mesh exported by CrimsonForge, or the result of
    :func:`sky2cd.donor_merge.merge_onto_donor`.
    """

    def __post_init__(self) -> None:
        self.positions = _array(self.positions, np.float32, (-1, 3), "positions")
        n = len(self.positions)
        self.normals = _optional_array(self.normals, np.float32, (n, 3), "normals", default=0.0)
        self.uvs = _optional_array(self.uvs, np.float32, (n, 2), "uvs", default=0.0)
        self.triangles = _optional_array(self.triangles, np.uint32, (-1, 3), "triangles", default=None)
        if self.bone_indices is None:
            self.bone_indices = np.zeros((n, 4), dtype=np.uint16)
        else:
            self.bone_indices = _array(self.bone_indices, np.uint16, (n, 4), "bone_indices")
        if self.bone_weights is None:
            self.bone_weights = np.zeros((n, 4), dtype=np.float32)
        else:
            self.bone_weights = _array(self.bone_weights, np.float32, (n, 4), "bone_weights")
            self.bone_weights = normalize_weights(self.bone_weights)
        if self.triangles is None:
            self.triangles = np.zeros((0, 3), dtype=np.uint32)
        if self.submesh_ids is not None:
            arr = np.asarray(self.submesh_ids, dtype=np.int32).reshape(-1)
            if arr.shape[0] != self.triangles.shape[0]:
                raise ValueError(
                    f"submesh_ids must have one entry per triangle "
                    f"(got {arr.shape[0]}, expected {self.triangles.shape[0]})"
                )
            self.submesh_ids = arr

    def copy_with(self, **changes: Any) -> "MeshIR":
        data = {
            "positions": self.positions.copy(),
            "normals": self.normals.copy(),
            "uvs": self.uvs.copy(),
            "triangles": self.triangles.copy(),
            "bone_names": list(self.bone_names),
            "bone_indices": self.bone_indices.copy(),
            "bone_weights": self.bone_weights.copy(),
            "materials": json.loads(json.dumps(self.materials)),
            "name": self.name,
            "submesh_ids": None if self.submesh_ids is None else self.submesh_ids.copy(),
        }
        data.update(changes)
        return replace(self, **data)

    @property
    def vertex_count(self) -> int:
        return int(self.positions.shape[0])


def _array(value: Any, dtype: np.dtype, shape: tuple[int, int], name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=dtype)
    if arr.ndim != 2 or arr.shape[1] != shape[1]:
        raise ValueError(f"{name} must have shape (n, {shape[1]})")
    if shape[0] >= 0 and arr.shape[0] != shape[0]:
        raise ValueError(f"{name} must have shape ({shape[0]}, {shape[1]})")
    return arr


def _optional_array(
    value: Any | None,
    dtype: np.dtype,
    shape: tuple[int, int],
    name: str,
    default: float | None,
) -> np.ndarray | None:
    if value is None:
        if default is None:
            return None
        return np.full(shape, default, dtype=dtype)
    return _array(value, dtype, shape, name)


def normalize_weights(weights: np.ndarray) -> np.ndarray:
    weights = np.asarray(weights, dtype=np.float32).copy()
    weights[weights < 0] = 0
    totals = weights.sum(axis=1, keepdims=True)
    nonzero = totals[:, 0] > 0
    weights[nonzero] /= totals[nonzero]
    return weights


def scale_mesh(mesh: MeshIR, factor: float) -> MeshIR:
    return mesh.copy_with(positions=mesh.positions * np.float32(factor))


def save_meshir(mesh: MeshIR, path: str | Path) -> Path:
    json_path = Path(path)
    if json_path.suffix != ".json":
        json_path = json_path.with_suffix(".meshir.json")
    npz_path = json_path.with_suffix(".npz")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    arrays = dict(
        positions=mesh.positions,
        normals=mesh.normals,
        uvs=mesh.uvs,
        triangles=mesh.triangles,
        bone_indices=mesh.bone_indices,
        bone_weights=mesh.bone_weights,
    )
    if mesh.submesh_ids is not None:
        arrays["submesh_ids"] = mesh.submesh_ids
    np.savez_compressed(npz_path, **arrays)
    metadata = {
        "schema": "sky2cd.meshir.v1",
        "name": mesh.name,
        "arrays": npz_path.name,
        "bone_names": mesh.bone_names,
        "materials": mesh.materials,
        "has_submesh_ids": mesh.submesh_ids is not None,
    }
    json_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return json_path


def load_meshir(path: str | Path) -> MeshIR:
    json_path = Path(path)
    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    if metadata.get("schema") != "sky2cd.meshir.v1":
        raise ValueError(f"Unsupported MeshIR schema in {json_path}")
    npz_path = json_path.with_name(metadata["arrays"])
    with np.load(npz_path) as data:
        submesh_ids = data["submesh_ids"] if metadata.get("has_submesh_ids") and "submesh_ids" in data else None
        return MeshIR(
            positions=data["positions"],
            normals=data["normals"],
            uvs=data["uvs"],
            triangles=data["triangles"],
            bone_names=list(metadata.get("bone_names", [])),
            bone_indices=data["bone_indices"],
            bone_weights=data["bone_weights"],
            materials=list(metadata.get("materials", [])),
            name=metadata.get("name", json_path.stem),
            submesh_ids=submesh_ids,
        )
