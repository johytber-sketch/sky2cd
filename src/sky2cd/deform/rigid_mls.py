from __future__ import annotations

from sky2cd.deform.base import Deformer
from sky2cd.meshir import MeshIR


class RigidMLSDeformer(Deformer):
    """TODO: implement rigid moving-least-squares deformation."""

    def deform(self, source_body: MeshIR, target_body: MeshIR, outfit: MeshIR) -> MeshIR:
        raise NotImplementedError(
            "Rigid MLS deformation is a placeholder. Implement a permission-safe rigid-MLS solver here."
        )
