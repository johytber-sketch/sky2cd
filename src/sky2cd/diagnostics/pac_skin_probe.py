"""Inspect a candidate skin layout observed in local PAR 0x01000903 PACs.

This is deliberately not wired into conversion, rig transfer, or PAC writing.
It does not establish that the candidate joint table maps to any skeleton.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SkinFieldCandidate:
    joint_table_indices: np.ndarray
    weight_bytes: np.ndarray

    @property
    def weights_unorm8(self) -> np.ndarray:
        """Scale explicit bytes only; never renormalize or invent a remainder."""
        return self.weight_bytes.astype(np.float64) / 255.0


def inspect_skin_candidate(
    records: np.ndarray, *, version: int, joint_table_count: int,
) -> SkinFieldCandidate:
    """Read two little-endian 3x10-bit fields and six explicit byte weights.

    Guards restrict this probe to the observed record envelope. Passing them
    does NOT prove format semantics, bone identities, bind pose or rig validity.
    Zero-weight entries retain their stored indices, including unused values.
    """
    if version != 0x01000903:
        raise ValueError("Unobserved PAC version; candidate skin layout is not applicable.")
    if records.dtype != np.uint8 or records.ndim != 2 or records.shape[1] != 40:
        raise ValueError("Candidate skin probe requires uint8 records with exactly 40 bytes per row.")
    if not 1 <= joint_table_count <= 1024:
        raise ValueError("Candidate joint table count must be in 1..1024.")
    words = records[:, 20:28].copy().view("<u4").reshape(-1, 2)
    if np.any(words >> 30) or np.any(records[:, 34:36]):
        raise ValueError("Unobserved nonzero padding bits/bytes; do not assume this candidate layout.")
    indices = np.column_stack([
        (words[:, word] >> (slot * 10)) & 0x3FF
        for word in range(2) for slot in range(3)
    ]).astype(np.uint16)
    weights = records[:, 28:34].copy()
    if np.any(indices[weights > 0] >= joint_table_count):
        raise ValueError("Active candidate index is outside the supplied joint table.")
    sums = weights.astype(np.int32).sum(axis=1)
    if np.any(np.abs(sums - 255) > 3):
        raise ValueError("Explicit weight bytes exceed a six-UNORM8 rounding envelope; layout unconfirmed.")
    return SkinFieldCandidate(indices, weights)
