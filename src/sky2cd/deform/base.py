from __future__ import annotations

from abc import ABC, abstractmethod

from sky2cd.meshir import MeshIR


class Deformer(ABC):
    """Interface for outfit deformation between source and target body shapes."""

    @abstractmethod
    def deform(self, source_body: MeshIR, target_body: MeshIR, outfit: MeshIR) -> MeshIR:
        raise NotImplementedError
