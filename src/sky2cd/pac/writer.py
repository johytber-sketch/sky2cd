from __future__ import annotations

from pathlib import Path
import struct

import numpy as np

from sky2cd.meshir import MeshIR

MAGIC = b"SPAC"
VERSION = 1
VERTEX_STRIDE = 40
HEADER_STRUCT = struct.Struct("<4sIIII3f3fIII")
VERTEX_STRUCT = struct.Struct("<3H2eIBBBB4B18x")


def write_pac(meshir: MeshIR, out_path: str | Path) -> Path:
    """Write an experimental single-LOD PAC-like mesh file.

    This follows the documented 40-byte vertex layout conceptually but remains
    unverified against real Crimson Desert files.
    """

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    center, half_extent = _bounds(meshir.positions)
    vertices = b"".join(_pack_vertex(meshir, i, center, half_extent) for i in range(meshir.vertex_count))
    indices = meshir.triangles.astype("<u4", copy=False).reshape(-1).tobytes()
    header = HEADER_STRUCT.pack(
        MAGIC,
        VERSION,
        meshir.vertex_count,
        int(meshir.triangles.size),
        VERTEX_STRIDE,
        *center.astype(float),
        *half_extent.astype(float),
        1,
        len(vertices),
        len(indices),
    )
    path.write_bytes(header + vertices + indices)
    return path


def read_experimental_header(path: str | Path) -> dict[str, int | tuple[float, float, float] | bytes]:
    raw = Path(path).read_bytes()[: HEADER_STRUCT.size]
    unpacked = HEADER_STRUCT.unpack(raw)
    return {
        "magic": unpacked[0],
        "version": unpacked[1],
        "vertex_count": unpacked[2],
        "index_count": unpacked[3],
        "vertex_stride": unpacked[4],
        "center": tuple(unpacked[5:8]),
        "half_extent": tuple(unpacked[8:11]),
        "section_count": unpacked[11],
        "vertex_buffer_size": unpacked[12],
        "index_buffer_size": unpacked[13],
    }


def _bounds(positions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(positions) == 0:
        return np.zeros(3, dtype=np.float32), np.ones(3, dtype=np.float32)
    minimum = positions.min(axis=0)
    maximum = positions.max(axis=0)
    center = ((minimum + maximum) * 0.5).astype(np.float32)
    half_extent = np.maximum((maximum - minimum) * 0.5, 1e-6).astype(np.float32)
    return center, half_extent


def _pack_vertex(mesh: MeshIR, index: int, center: np.ndarray, half_extent: np.ndarray) -> bytes:
    position = mesh.positions[index]
    normalized = np.clip((position - center) / half_extent, -1.0, 1.0)
    quantized = np.rint((normalized * 0.5 + 0.5) * 65535.0).astype(np.uint16)
    uv = mesh.uvs[index].astype(np.float16)
    normal = _pack_r10g10b10a2(mesh.normals[index])
    bone_indices = np.clip(mesh.bone_indices[index], 0, 255).astype(np.uint8)
    bone_weights = np.rint(np.clip(mesh.bone_weights[index], 0.0, 1.0) * 255.0).astype(np.uint8)
    return VERTEX_STRUCT.pack(
        int(quantized[0]),
        int(quantized[1]),
        int(quantized[2]),
        uv[0],
        uv[1],
        normal,
        *[int(x) for x in bone_indices],
        *[int(x) for x in bone_weights],
    )


def _pack_r10g10b10a2(normal: np.ndarray) -> int:
    n = np.asarray(normal, dtype=np.float32)
    length = float(np.linalg.norm(n))
    if length > 1e-8:
        n = n / length
    packed_xyz = np.rint(np.clip(n, -1.0, 1.0) * 511.0).astype(np.int32) & 0x3FF
    x, y, z = (int(component) for component in packed_xyz)
    return x | (y << 10) | (z << 20) | (3 << 30)
