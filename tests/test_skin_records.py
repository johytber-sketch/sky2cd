from dataclasses import FrozenInstanceError, replace
import struct

import pytest

from sky2cd.pac.skin_records import (
    JointHashMapping, NativeSkinRecord, PabNamedRecord, SkinRecordContext,
    SkinRecordLayout, decode_skin_record, encode_skin_record, resolve_active_influences,
)


def context(hashes=tuple(range(1024))):
    return SkinRecordContext(SkinRecordLayout.OBSERVED_PAR_01000903_SKIN40, hashes, "synthetic fixture")


def raw_record(indices=(7, 290, 1023, 13, 511, 812), weights=(100, 60, 40, 30, 20, 5)):
    raw = bytearray(range(40))
    for word in range(2):
        struct.pack_into("<I", raw, 20 + 4 * word,
                         sum(index << (slot * 10) for slot, index in enumerate(indices[word * 3:word * 3 + 3])))
    raw[28:34] = bytes(weights)
    raw[34:36] = b"\0\0"
    return bytes(raw)


def test_six_fields_and_all_opaque_bytes_repacked_exactly():
    raw = raw_record()
    record = decode_skin_record(raw, context=context())
    assert record.joint_table_indices == (7, 290, 1023, 13, 511, 812)
    assert record.weight_bytes == (100, 60, 40, 30, 20, 5)
    assert encode_skin_record(record) == raw
    assert record.raw_record[:20] == bytes(range(20))
    assert record.raw_record[34:] == b"\0\0\x24\x25\x26\x27"


@pytest.mark.parametrize("marker", [0, 0x3C000000, 0xFFFFFFFF])
def test_opaque_marker_is_not_a_layout_discriminator(marker):
    raw = bytearray(raw_record())
    struct.pack_into("<I", raw, 12, marker)
    raw[36:40] = b"\xff\x00\x7f\x80"
    record = decode_skin_record(bytes(raw), context=context())
    assert encode_skin_record(record) == bytes(raw)


def test_immutable_record_and_context_and_no_four_slot_edit_path():
    record = decode_skin_record(raw_record(), context=context())
    with pytest.raises(FrozenInstanceError):
        record.weight_bytes = (255, 0, 0, 0)
    with pytest.raises(TypeError):
        record.weight_bytes[0] = 255
    with pytest.raises(FrozenInstanceError):
        record.context.joint_hashes = (0,)
    with pytest.raises(ValueError):
        replace(record, weight_bytes=(255, 0, 0, 0))
    with pytest.raises(ValueError):
        encode_skin_record({"bone_weights": [1, 0, 0, 0]})


@pytest.mark.parametrize("total", [252, 253, 255, 257, 258])
def test_raw_quantization_not_normalized(total):
    record = decode_skin_record(raw_record(weights=(100, 60, 40, 30, 20, total - 250)), context=context())
    assert sum(record.weight_bytes) == total
    assert sum(record.weights_unorm8) == pytest.approx(total / 255.0)
    assert encode_skin_record(record) == record.raw_record


@pytest.mark.parametrize("raw", [b"", bytes(39), bytes(41), bytes(80), bytearray(40)])
def test_rejects_wrong_size_or_mutable_buffer(raw):
    with pytest.raises(ValueError):
        decode_skin_record(raw, context=context())


@pytest.mark.parametrize("offset,mask", [(23, 0x40), (23, 0x80), (27, 0x40), (27, 0x80), (34, 1), (35, 1)])
def test_unobserved_padding_rejected_not_zeroed(offset, mask):
    raw = bytearray(raw_record())
    raw[offset] |= mask
    with pytest.raises(ValueError, match="padding"):
        decode_skin_record(bytes(raw), context=context())


@pytest.mark.parametrize("weights", [(0, 0, 0, 0, 0, 0), (255, 255, 0, 0, 0, 0)])
def test_rejects_outside_probe_rounding_envelope(weights):
    with pytest.raises(ValueError, match="rounding envelope"):
        decode_skin_record(raw_record(weights=weights), context=context())


@pytest.mark.parametrize("hashes", [(), (1, 1), (-1,), (2**32,), (True,), [1], tuple(range(1025))])
def test_rejects_invalid_joint_tables(hashes):
    with pytest.raises(ValueError):
        context(hashes)


@pytest.mark.parametrize("layout", [None, "observed-par-01000903-skin40", 0x01000903, 40])
def test_no_version_stride_or_string_autodetection(layout):
    with pytest.raises(ValueError):
        SkinRecordContext(layout, (10,), "fixture")


def test_requires_context_and_evidence():
    with pytest.raises(TypeError):
        decode_skin_record(raw_record())
    with pytest.raises(ValueError):
        decode_skin_record(raw_record(), context=None)
    with pytest.raises(ValueError):
        SkinRecordContext(SkinRecordLayout.OBSERVED_PAR_01000903_SKIN40, (10,), " ")


def test_active_bounds_and_inactive_indices():
    raw = raw_record((0, 1023, 0, 0, 0, 0), (255, 0, 0, 0, 0, 0))
    ctx = context((123,))
    record = decode_skin_record(raw, context=ctx)
    mapping = JointHashMapping(ctx, (PabNamedRecord(0, 123, "Joint"),))
    assert record.joint_table_indices[1] == 1023
    assert len(resolve_active_influences(record, mapping)) == 1
    assert encode_skin_record(record) == raw
    with pytest.raises(ValueError, match="outside"):
        decode_skin_record(raw_record((0, 1, 0, 0, 0, 0), (254, 1, 0, 0, 0, 0)), context=ctx)


def test_all_six_resolve_by_hash_not_ordinal():
    ctx = context((11, 22, 33, 44, 55, 66))
    pab = tuple(PabNamedRecord(i, h, f"Joint_{h}") for i, h in enumerate(reversed(ctx.joint_hashes)))
    mapping = JointHashMapping(ctx, pab)
    record = decode_skin_record(raw_record(tuple(range(6))), context=ctx)
    resolved = resolve_active_influences(record, mapping)
    assert len(resolved) == 6
    assert tuple(r.joint.pab_record_index for r in resolved) == (5, 4, 3, 2, 1, 0)
    assert tuple(r.weight_byte for r in resolved) == record.weight_bytes
    assert tuple(r.joint.pab_name for r in resolved) == tuple(f"Joint_{h}" for h in ctx.joint_hashes)
    other = JointHashMapping(context(tuple(reversed(ctx.joint_hashes))), pab)
    with pytest.raises(ValueError, match="same explicit context"):
        resolve_active_influences(record, other)


@pytest.mark.parametrize("records", [
    (),
    (PabNamedRecord(1, 11, "A"),),
    (PabNamedRecord(0, 11, "A"), PabNamedRecord(1, 11, "B")),
    (PabNamedRecord(0, 11, "A"), PabNamedRecord(1, 22, "A")),
    (PabNamedRecord(0, 22, "B"),),
])
def test_rejects_missing_ambiguous_or_reordered_pab_mapping(records):
    with pytest.raises(ValueError):
        JointHashMapping(context((11,)), records)


@pytest.mark.parametrize("args", [(-1, 1, "A"), (0, -1, "A"), (0, 1, ""), (0, 1, "A\0")])
def test_rejects_invalid_named_record(args):
    with pytest.raises(ValueError):
        PabNamedRecord(*args)
