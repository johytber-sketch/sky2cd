from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from sky2cd.meshir import MeshIR, normalize_weights


@dataclass(frozen=True)
class WeightSidecar:
    bone_names: list[str]
    vertices: list[dict[str, Any]]


def write_sidecar(mesh: MeshIR, path: str | Path) -> Path:
    sidecar_path = Path(path)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "sky2cd.cfmeta.v1",
        "mesh_name": mesh.name,
        "bone_names": mesh.bone_names,
        "vertices": [
            {
                "index": int(i),
                "position": mesh.positions[i].astype(float).tolist(),
                "bone_indices": mesh.bone_indices[i].astype(int).tolist(),
                "bone_weights": mesh.bone_weights[i].astype(float).tolist(),
            }
            for i in range(mesh.vertex_count)
        ],
    }
    sidecar_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return sidecar_path


def read_sidecar(path: str | Path) -> WeightSidecar:
    sidecar_path = Path(path)
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "sky2cd.cfmeta.v1":
        raise ValueError(f"Unsupported sidecar schema in {sidecar_path}")
    return WeightSidecar(
        bone_names=list(payload.get("bone_names", [])),
        vertices=list(payload.get("vertices", [])),
    )


def reapply_weights(
    original_mesh: MeshIR,
    edited_mesh: MeshIR,
    sidecar: WeightSidecar | str | Path | None = None,
    *,
    position_tolerance: float = 1e-5,
) -> MeshIR:
    """Restore skin weights to an edited mesh using a sidecar or original mesh fallback.

    **Vectorized** (real, confirmed bottleneck fixed): the previous
    implementation ran one Python-level `tree.query(position)` call per
    vertex -- 50,000 separate Python-to-C calls for a 50k-vertex mesh. This
    now does the identical two-tier match (same-index exact match first,
    nearest-neighbor fallback second) but as two batch operations: a single
    vectorized distance check for the "same index" fast path (this is NOT a
    nearest-any-source-vertex check -- it deliberately only compares each
    edited vertex `i` against source vertex `i`, matching the original
    per-vertex loop's semantics exactly, since two source vertices sitting
    at nearly the same position must not be confused with each other), then
    one batch `tree.query(..., workers=-1)` call for every vertex that
    fast path didn't resolve.
    """

    source = _source_from_sidecar_or_original(original_mesh, sidecar)
    src_positions, src_indices, src_weights, bone_names = source
    n_edited = edited_mesh.vertex_count
    n_common = min(n_edited, len(src_positions))

    match = np.zeros(n_edited, dtype=np.int64)
    exact_resolved = np.zeros(n_edited, dtype=bool)
    if n_common:
        same_index_distance = np.linalg.norm(
            edited_mesh.positions[:n_common] - src_positions[:n_common], axis=1
        )
        exact_mask = same_index_distance <= position_tolerance
        match[:n_common][exact_mask] = np.nonzero(exact_mask)[0]
        exact_resolved[:n_common] = exact_mask

    unresolved = ~exact_resolved
    if unresolved.any():
        if len(src_positions):
            tree = cKDTree(src_positions)
            _, nearest = tree.query(edited_mesh.positions[unresolved], k=1, workers=-1)
            match[unresolved] = np.atleast_1d(nearest)
        else:
            match[unresolved] = 0

    out_indices = src_indices[match] if len(src_indices) else np.zeros((n_edited, 4), dtype=np.uint16)
    out_weights = src_weights[match] if len(src_weights) else np.zeros((n_edited, 4), dtype=np.float32)

    return edited_mesh.copy_with(
        bone_names=bone_names or edited_mesh.bone_names,
        bone_indices=out_indices.astype(np.uint16),
        bone_weights=normalize_weights(out_weights.astype(np.float32)),
    )


def _source_from_sidecar_or_original(
    original_mesh: MeshIR, sidecar: WeightSidecar | str | Path | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    if isinstance(sidecar, WeightSidecar):
        return _source_from_vertices(sidecar.vertices, sidecar.bone_names)
    if sidecar is not None:
        sidecar_path = Path(sidecar)
        if sidecar_path.exists():
            loaded = read_sidecar(sidecar_path)
            return _source_from_vertices(loaded.vertices, loaded.bone_names)

    return (
        original_mesh.positions,
        original_mesh.bone_indices,
        original_mesh.bone_weights,
        list(original_mesh.bone_names),
    )


def _source_from_vertices(vertices: list[dict[str, Any]], bone_names: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    ordered = sorted(vertices, key=lambda item: int(item["index"]))
    positions = np.asarray([item["position"] for item in ordered], dtype=np.float32)
    indices = np.asarray([item["bone_indices"] for item in ordered], dtype=np.uint16)
    weights = normalize_weights(np.asarray([item["bone_weights"] for item in ordered], dtype=np.float32))
    return positions, indices, weights, list(bone_names)
