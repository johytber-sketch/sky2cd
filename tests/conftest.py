import numpy as np
import pytest

from sky2cd.meshir import MeshIR
from sky2cd.presets import build_custom_preset


@pytest.fixture
def fitting_config(tmp_path):
    """A nonplanar, identical-topology pair for offline wiring tests, not a real body."""
    body = MeshIR(
        positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]),
        triangles=np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]),
    )
    return build_custom_preset(body, body, "synthetic_test_pair", tmp_path / "references")
