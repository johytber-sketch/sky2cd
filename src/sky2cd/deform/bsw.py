from __future__ import annotations

from sky2cd.deform.base import Deformer
from sky2cd.meshir import MeshIR


class BSWDeformer(Deformer):
    """TODO: implement a BSW-style thickness-preserving deformation pass."""

    def deform(self, source_body: MeshIR, target_body: MeshIR, outfit: MeshIR) -> MeshIR:
        raise NotImplementedError(
            "BSW-style deformation is a placeholder. Implement a permission-safe thickness-preserving solver here."
        )
