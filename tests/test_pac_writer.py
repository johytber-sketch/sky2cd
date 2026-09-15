import os

import numpy as np

from sky2cd.meshir import MeshIR
from sky2cd.pac.writer import HEADER_STRUCT, VERTEX_STRIDE, read_experimental_header, write_pac


def test_pac_writer_produces_structural_header_and_vertex_buffer(tmp_path):
    mesh = MeshIR(
        positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32),
        normals=np.array([[0, 0, 1]] * 3, dtype=np.float32),
        uvs=np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        bone_indices=np.zeros((3, 4), dtype=np.uint16),
        bone_weights=np.array([[1, 0, 0, 0]] * 3, dtype=np.float32),
    )
    path = write_pac(mesh, tmp_path / "tiny.pac")
    header = read_experimental_header(path)

    assert header["magic"] == b"SPAC"
    assert header["vertex_count"] == 3
    assert header["index_count"] == 3
    assert header["vertex_stride"] == VERTEX_STRIDE
    assert header["vertex_buffer_size"] == 3 * VERTEX_STRIDE
    assert os.path.getsize(path) == HEADER_STRUCT.size + 3 * VERTEX_STRIDE + 3 * 4
