import numpy as np

from sky2cd.meshir import MeshIR


def recompute_normals(mesh: MeshIR) -> MeshIR:
    """Area-weighted normals without welding seam vertices."""
    normals = np.zeros_like(mesh.positions, dtype=np.float64)
    t = mesh.positions.astype(np.float64)[mesh.triangles]
    faces = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    for corner in range(3):
        np.add.at(normals, mesh.triangles[:, corner], faces)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=mesh.normals.astype(np.float64).copy(), where=lengths > 1e-12)
    return mesh.copy_with(normals=normals.astype(np.float32))
