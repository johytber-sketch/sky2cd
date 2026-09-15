import numpy as np
import pytest

from sky2cd.weights.transform_checks import (
    affine_difference, change_basis, inverse_pair_errors, local_to_global, skin_bind_closure,
)


def transform():
    return np.array([[0, -2, 0, 4], [3, 0, 0, -5], [0, 0, 0.5, 7], [0, 0, 0, 1.0]])


def test_row_column_chain_and_wrong_order():
    parent = transform()
    local = np.eye(4)
    local[:3, 3] = [1, 2, 3]
    expected = parent @ local
    np.testing.assert_array_equal(local_to_global(local, parent, convention="column"), expected)
    np.testing.assert_array_equal(local_to_global(local.T, parent.T, convention="row"), expected.T)
    assert affine_difference(local @ parent, expected, convention="column").max_abs > 1


def test_inverse_pair_does_not_discard_scale_or_replace_bad_inverse():
    matrix = transform()
    assert max(inverse_pair_errors(matrix, np.linalg.inv(matrix), convention="column")) < 1e-14
    assert max(inverse_pair_errors(matrix.T, np.linalg.inv(matrix).T, convention="row")) < 1e-14
    assert max(inverse_pair_errors(matrix, np.eye(4), convention="column")) > 1
    np.testing.assert_array_equal(local_to_global(np.eye(4), matrix, convention="column"), matrix)


def test_stored_skin_bind_and_nonidentity_skin_space():
    node = transform()
    skin = np.eye(4)
    skin[:3, 3] = [11, -12, 13]
    bind = np.linalg.inv(node) @ np.linalg.inv(skin)
    assert skin_bind_closure(skin, node, bind, convention="column").max_abs < 1e-14
    assert skin_bind_closure(skin.T, node.T, bind.T, convention="row").max_abs < 1e-14
    assert skin_bind_closure(np.eye(4), node, bind, convention="column").max_abs > 1
    changed_node = node.copy()
    changed_node[0, 3] += 0.2
    residual = skin_bind_closure(skin, changed_node, bind, convention="column")
    assert residual.translation_norm == pytest.approx(0.2)


def test_coordinate_basis_conjugation_preserves_point_action_and_residual():
    matrix = transform()
    basis = np.eye(4)
    basis[:3, :3] = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]]) * 0.0142875
    assert np.linalg.det(basis[:3, :3]) > 0
    result = change_basis(matrix, basis, convention="column")
    point = np.array([0.5, 2, 4, 1])
    np.testing.assert_allclose(result @ (basis @ point), basis @ (matrix @ point), atol=1e-14)
    np.testing.assert_allclose(change_basis(matrix.T, basis.T, convention="row"), result.T)
    np.testing.assert_allclose(change_basis(result, np.linalg.inv(basis), convention="column"), matrix)
    shifted = matrix.copy()
    shifted[0, 3] += 2
    before = affine_difference(shifted, matrix, convention="column")
    after = affine_difference(change_basis(shifted, basis, convention="column"), result, convention="column")
    assert after.translation_norm == pytest.approx(before.translation_norm * 0.0142875)


@pytest.mark.parametrize("bad", [np.eye(3), np.zeros((4, 4)), np.full((4, 4), np.nan)])
def test_reject_malformed_or_singular(bad):
    with pytest.raises(ValueError):
        inverse_pair_errors(bad, np.eye(4), convention="column")


def test_reject_undeclared_convention_and_untransposed_row_data():
    with pytest.raises(ValueError, match="convention"):
        local_to_global(np.eye(4), np.eye(4), convention="guess")
    with pytest.raises(ValueError, match="affine"):
        affine_difference(transform(), np.eye(4), convention="row")


def test_no_mutation_and_no_acceptance_threshold():
    matrix = transform()
    original = matrix.copy()
    result = local_to_global(np.eye(4), matrix, convention="column")
    result[0, 0] = 99
    np.testing.assert_array_equal(matrix, original)
    shifted = matrix.copy()
    shifted[0, 3] += 1e-5
    assert affine_difference(shifted, matrix, convention="column").translation_norm > 0


def test_row_scale_compensation_includes_translation_and_is_not_commutative():
    local = transform().T
    pre = np.diag([0.8, 0.8, 0.8, 1])
    post = np.diag([1.25, 1.25, 1.25, 1])
    parent = np.eye(4)
    parent[3, :3] = [2, 3, 4]
    expected = (pre @ local @ post) @ parent
    np.testing.assert_allclose(
        local_to_global(pre @ local @ post, parent, convention="row"), expected,
    )
    only_linear = pre @ local @ post
    only_linear[3, :3] = local[3, :3]
    assert affine_difference(
        local_to_global(only_linear, parent, convention="row"), expected, convention="row",
    ).translation_norm > 1
    assert affine_difference(
        local_to_global(local @ pre @ post, parent, convention="row"), expected, convention="row",
    ).translation_norm > 1
