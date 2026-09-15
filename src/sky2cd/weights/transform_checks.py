"""Pure affine checks with explicit storage convention, not rig interpretation.

No inferred parent, pose, scale correction, weight modification or threshold-based
acceptance is performed. Residual translation units are the caller's input units.
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np

Convention = Literal["row", "column"]


def _column(matrix: np.ndarray, convention: Convention) -> np.ndarray:
    if convention not in ("row", "column"):
        raise ValueError("Explicit 'row' or 'column' vector convention is required.")
    value = np.array(matrix, dtype=np.float64, copy=True)
    if value.shape != (4, 4) or not np.isfinite(value).all():
        raise ValueError("Expected a finite 4x4 affine matrix.")
    if convention == "row":
        value = value.T.copy()
    if not np.allclose(value[3], [0, 0, 0, 1], rtol=0, atol=1e-6):
        raise ValueError("Matrix is not affine in the declared convention.")
    if np.linalg.slogdet(value[:3, :3])[0] == 0:
        raise ValueError("Singular linear transform is not an invertible bind frame.")
    return value


def _stored(column: np.ndarray, convention: Convention) -> np.ndarray:
    return column.T.copy() if convention == "row" else column.copy()


@dataclass(frozen=True)
class TransformResidual:
    max_abs: float
    linear_max_abs: float
    translation_norm: float


def affine_difference(
    actual: np.ndarray, expected: np.ndarray, *, convention: Convention,
) -> TransformResidual:
    difference = _column(actual, convention) - _column(expected, convention)
    return TransformResidual(
        float(np.max(np.abs(difference))),
        float(np.max(np.abs(difference[:3, :3]))),
        float(np.linalg.norm(difference[:3, 3])),
    )


def local_to_global(
    local: np.ndarray, parent_global: np.ndarray, *, convention: Convention,
) -> np.ndarray:
    """Column: parent @ local. Row: local @ parent. Preserve non-unit scale."""
    result = _column(parent_global, convention) @ _column(local, convention)
    return _stored(result, convention)


def inverse_pair_errors(
    transform: np.ndarray, stored_inverse: np.ndarray, *, convention: Convention,
) -> tuple[float, float]:
    """Check both product orders; do not silently recompute a supplied inverse."""
    matrix = _column(transform, convention)
    inverse = _column(stored_inverse, convention)
    identity = np.eye(4)
    return (
        float(np.max(np.abs(matrix @ inverse - identity))),
        float(np.max(np.abs(inverse @ matrix - identity))),
    )


def skin_bind_closure(
    global_to_skin: np.ndarray, node_to_global: np.ndarray, skin_to_bone: np.ndarray,
    *, convention: Convention,
) -> TransformResidual:
    """Test skin -> bone -> global -> skin against identity, not a fitted pose."""
    result = (
        _column(global_to_skin, convention)
        @ _column(node_to_global, convention)
        @ _column(skin_to_bone, convention)
    )
    return affine_difference(result, np.eye(4), convention="column")


def change_basis(
    transform: np.ndarray, old_to_new: np.ndarray, *, convention: Convention,
) -> np.ndarray:
    """Conjugate by an explicit coordinate/unit transform; never infer one."""
    matrix = _column(transform, convention)
    basis = _column(old_to_new, convention)
    result = basis @ matrix @ np.linalg.inv(basis)
    return _stored(result, convention)
