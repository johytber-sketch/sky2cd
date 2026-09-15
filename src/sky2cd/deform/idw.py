from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from sky2cd.deform.base import Deformer
from sky2cd.meshir import MeshIR


class IDWDeformer(Deformer):
    """Inverse-distance weighted displacement transfer from body to outfit."""

    def __init__(self, neighbors: int = 8, power: float = 2.0, epsilon: float = 1e-8) -> None:
        if neighbors < 1:
            raise ValueError("neighbors must be >= 1")
        if power <= 0:
            raise ValueError("power must be > 0")
        self.neighbors = neighbors
        self.power = power
        self.epsilon = epsilon
        # Real, confirmed perf win for multi-piece archives (e.g. the real
        # Sherwood Huntress outfit's 4 separate meshes): source_body never
        # changes across pieces within one `pipeline.convert()` run, so
        # rebuilding a cKDTree from its ~10k-20k vertices for every single
        # piece was pure waste. Cached by the source_body positions array's
        # identity (`id()`), which is stable for the lifetime of this
        # deformer instance since `pipeline._process_mesh` always passes the
        # same `source_body` MeshIR object through unchanged.
        self._tree_cache: dict[int, cKDTree] = {}

    def _tree_for(self, source_body: MeshIR) -> cKDTree:
        key = id(source_body.positions)
        tree = self._tree_cache.get(key)
        if tree is None:
            tree = cKDTree(source_body.positions)
            self._tree_cache[key] = tree
        return tree

    def deform(self, source_body: MeshIR, target_body: MeshIR, outfit: MeshIR) -> MeshIR:
        if source_body.vertex_count != target_body.vertex_count:
            raise ValueError("source_body and target_body must have the same vertex count for IDW")
        if source_body.vertex_count == 0:
            return outfit.copy_with()

        displacements = target_body.positions - source_body.positions
        k = min(self.neighbors, source_body.vertex_count)
        distances, indices = self._tree_for(source_body).query(outfit.positions, k=k, workers=-1)
        if k == 1:
            distances = distances[:, None]
            indices = indices[:, None]

        exact = distances <= self.epsilon
        weights = 1.0 / np.maximum(distances, self.epsilon) ** self.power
        weights[exact] = 0.0
        exact_rows = exact.any(axis=1)
        if exact_rows.any():
            weights[exact_rows] = exact[exact_rows].astype(np.float64)
        weights /= weights.sum(axis=1, keepdims=True)
        delta = (displacements[indices] * weights[..., None]).sum(axis=1).astype(np.float32)
        return outfit.copy_with(positions=outfit.positions + delta)
