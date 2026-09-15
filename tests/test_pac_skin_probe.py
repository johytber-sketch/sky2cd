import struct

import numpy as np
import pytest

from sky2cd.diagnostics.pac_skin_probe import inspect_skin_candidate


def _record(indices=(7, 290, 1023, 13, 511, 812), weights=(100, 60, 40, 30, 20, 5)):
    record = bytearray(40)
    for word in range(2):
        a, b, c = (int(value) for value in indices[word * 3:word * 3 + 3])
        struct.pack_into("<I", record, 20 + word * 4, a | (b << 10) | (c << 20))
    record[28:34] = bytes(weights)
    return np.frombuffer(bytes(record), dtype=np.uint8).reshape(1, 40)


def test_candidate_retains_six_explicit_influences_and_two_word_boundaries():
    records = _record()
    candidate = inspect_skin_candidate(records, version=0x01000903, joint_table_count=1024)
    np.testing.assert_array_equal(candidate.joint_table_indices, [[7, 290, 1023, 13, 511, 812]])
    np.testing.assert_array_equal(candidate.weight_bytes, [[100, 60, 40, 30, 20, 5]])
    np.testing.assert_array_equal(candidate.weights_unorm8, candidate.weight_bytes / 255.0)
    rebuilt = _record(tuple(candidate.joint_table_indices[0]), tuple(candidate.weight_bytes[0]))
    np.testing.assert_array_equal(records, rebuilt)


@pytest.mark.parametrize("total", [253, 255, 257])
def test_candidate_does_not_normalize_or_invent_implicit_weights(total):
    candidate = inspect_skin_candidate(
        _record(weights=(100, 60, 40, 30, 20, total - 250)),
        version=0x01000903, joint_table_count=1024,
    )
    assert candidate.weights_unorm8.sum() == pytest.approx(total / 255)


def test_zero_weight_retains_unused_index_without_turning_it_into_an_influence():
    candidate = inspect_skin_candidate(
        _record(indices=(1, 999, 0, 0, 0, 0), weights=(255, 0, 0, 0, 0, 0)),
        version=0x01000903, joint_table_count=10,
    )
    assert candidate.joint_table_indices[0, 1] == 999
    assert candidate.weights_unorm8[0, 1] == 0


@pytest.mark.parametrize("damage", ["version", "stride", "padding_bits", "padding_bytes", "index", "sum"])
def test_candidate_refuses_unobserved_layout(damage):
    records = _record().copy()
    version, count = 0x01000903, 1024
    if damage == "version":
        version = 0
    elif damage == "stride":
        records = records[:, :36]
    elif damage == "padding_bits":
        records[0, 23] |= 0x80
    elif damage == "padding_bytes":
        records[0, 34] = 1
    elif damage == "index":
        count = 100
    else:
        records[0, 28:34] = 0
    with pytest.raises(ValueError):
        inspect_skin_candidate(records, version=version, joint_table_count=count)
