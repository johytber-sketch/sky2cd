"""Explicitly selected, record-only native skin codec; not a PAC parser/writer.

Preserves six raw influences separately from MeshIR. The observed layout needs
caller-supplied evidence and an actual joint hash table, not version/stride
autodetection. Hash matches identify named PAB records, not validated rest poses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import struct

import numpy as np

from sky2cd.diagnostics.pac_skin_probe import inspect_skin_candidate


class SkinRecordLayout(Enum):
    OBSERVED_PAR_01000903_SKIN40 = "observed-par-01000903-skin40"


def _uint(value: int, bits: int, name: str) -> None:
    if type(value) is not int or not 0 <= value < (1 << bits):
        raise ValueError(f"{name} must be an unsigned {bits}-bit Python integer.")


@dataclass(frozen=True, slots=True)
class SkinRecordContext:
    layout: SkinRecordLayout
    joint_hashes: tuple[int, ...]
    evidence: str

    def __post_init__(self) -> None:
        if self.layout is not SkinRecordLayout.OBSERVED_PAR_01000903_SKIN40:
            raise ValueError("Explicit supported skin layout selection is required.")
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise ValueError("Supply the record/table provenance and layout evidence.")
        if type(self.joint_hashes) is not tuple or not 1 <= len(self.joint_hashes) <= 1024:
            raise ValueError("Supply an immutable actual joint hash table of 1..1024 entries.")
        for value in self.joint_hashes:
            _uint(value, 32, "Joint hash")
        if len(set(self.joint_hashes)) != len(self.joint_hashes):
            raise ValueError("Ambiguous duplicate hashes in joint table.")


@dataclass(frozen=True, slots=True)
class NativeSkinRecord:
    raw_record: bytes
    context: SkinRecordContext
    joint_table_indices: tuple[int, ...] = field(init=False)
    weight_bytes: tuple[int, ...] = field(init=False)

    def __post_init__(self) -> None:
        if type(self.raw_record) is not bytes or len(self.raw_record) != 40:
            raise ValueError("Native skin record must be exactly 40 immutable bytes.")
        if not isinstance(self.context, SkinRecordContext):
            raise ValueError("An explicit SkinRecordContext is required.")
        candidate = inspect_skin_candidate(
            np.frombuffer(self.raw_record, dtype=np.uint8).reshape(1, 40),
            version=0x01000903,
            joint_table_count=len(self.context.joint_hashes),
        )
        object.__setattr__(self, "joint_table_indices", tuple(map(int, candidate.joint_table_indices[0])))
        object.__setattr__(self, "weight_bytes", tuple(map(int, candidate.weight_bytes[0])))

    @property
    def weights_unorm8(self) -> tuple[float, ...]:
        """Explicit byte/255 values, whose sum need not be exactly one."""
        return tuple(value / 255.0 for value in self.weight_bytes)


def decode_skin_record(raw_record: bytes, *, context: SkinRecordContext) -> NativeSkinRecord:
    return NativeSkinRecord(raw_record, context)


def encode_skin_record(record: NativeSkinRecord) -> bytes:
    """Repack unchanged decoded fields into preserved bytes; no editing API."""
    if not isinstance(record, NativeSkinRecord):
        raise ValueError("Expected a validated NativeSkinRecord, not MeshIR or raw arrays.")
    result = bytearray(record.raw_record)
    for word in range(2):
        indices = record.joint_table_indices[word * 3:word * 3 + 3]
        packed = sum(index << (10 * slot) for slot, index in enumerate(indices))
        struct.pack_into("<I", result, 20 + word * 4, packed)
    result[28:34] = bytes(record.weight_bytes)
    return bytes(result)


@dataclass(frozen=True, slots=True)
class PabNamedRecord:
    record_index: int
    joint_hash: int
    name: str

    def __post_init__(self) -> None:
        _uint(self.record_index, 32, "PAB record index")
        _uint(self.joint_hash, 32, "PAB joint hash")
        if not isinstance(self.name, str) or not self.name or "\x00" in self.name:
            raise ValueError("PAB record must have a nonempty name without NUL.")


@dataclass(frozen=True, slots=True)
class JointHashMatch:
    joint_table_index: int
    joint_hash: int
    pab_record_index: int
    pab_name: str


@dataclass(frozen=True, slots=True)
class JointHashMapping:
    context: SkinRecordContext
    pab_records: tuple[PabNamedRecord, ...]
    entries: tuple[JointHashMatch, ...] = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.context, SkinRecordContext):
            raise ValueError("An explicit SkinRecordContext is required.")
        if type(self.pab_records) is not tuple or not self.pab_records:
            raise ValueError("Supply immutable named PAB records in their original order.")
        for index, record in enumerate(self.pab_records):
            if not isinstance(record, PabNamedRecord) or record.record_index != index:
                raise ValueError("PAB record indices must match original contiguous record order.")
        by_hash = {record.joint_hash: record for record in self.pab_records}
        if len(by_hash) != len(self.pab_records):
            raise ValueError("Ambiguous duplicate hashes in PAB records.")
        if len({record.name for record in self.pab_records}) != len(self.pab_records):
            raise ValueError("Ambiguous duplicate names in PAB records.")
        matches = []
        for index, joint_hash in enumerate(self.context.joint_hashes):
            if joint_hash not in by_hash:
                raise ValueError(f"Joint table index {index}, hash 0x{joint_hash:08x}, has no PAB match.")
            record = by_hash[joint_hash]
            matches.append(JointHashMatch(index, joint_hash, record.record_index, record.name))
        object.__setattr__(self, "entries", tuple(matches))


@dataclass(frozen=True, slots=True)
class NamedSkinInfluence:
    slot: int
    weight_byte: int
    joint: JointHashMatch


def resolve_active_influences(
    record: NativeSkinRecord, mapping: JointHashMapping,
) -> tuple[NamedSkinInfluence, ...]:
    """Resolve nonzero slots by hash; never assume PAC and PAB ordinals agree."""
    if record.context != mapping.context:
        raise ValueError("Skin record and joint mapping must use the same explicit context.")
    return tuple(
        NamedSkinInfluence(slot, weight, mapping.entries[index])
        for slot, (index, weight) in enumerate(zip(record.joint_table_indices, record.weight_bytes))
        if weight > 0
    )
