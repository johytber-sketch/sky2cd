from __future__ import annotations

from dataclasses import dataclass, field
import json
import warnings
from importlib import resources
from pathlib import Path


@dataclass(frozen=True)
class CDSlotMapping:
    skyrim_slot: str
    skyrim_name: str
    cd_slot_name: str | None
    cd_hash: str | None
    status: str
    merge_into: str | None = None
    reason: str | None = None


@dataclass
class MappingReport:
    mapped: list[CDSlotMapping] = field(default_factory=list)
    merged: list[CDSlotMapping] = field(default_factory=list)
    unsupported: list[CDSlotMapping] = field(default_factory=list)

    def add(self, mapping: CDSlotMapping) -> None:
        if mapping.status == "mapped":
            self.mapped.append(mapping)
        elif mapping.status == "merge":
            self.merged.append(mapping)
        else:
            self.unsupported.append(mapping)

    def to_dict(self) -> dict[str, list[dict[str, str | None]]]:
        return {
            "mapped": [_mapping_dict(item) for item in self.mapped],
            "merged": [_mapping_dict(item) for item in self.merged],
            "unsupported": [_mapping_dict(item) for item in self.unsupported],
        }


def load_slot_mappings(path: str | Path | None = None) -> dict[str, CDSlotMapping]:
    if path is None:
        text = resources.files("sky2cd.data").joinpath("slot_mappings.json").read_text(encoding="utf-8")
    else:
        text = Path(path).read_text(encoding="utf-8")
    payload = json.loads(text)
    return {
        str(slot): CDSlotMapping(
            skyrim_slot=str(slot),
            skyrim_name=str(data["skyrim_name"]),
            cd_slot_name=data.get("cd_slot_name"),
            cd_hash=data.get("cd_hash"),
            status=str(data["status"]),
            merge_into=data.get("merge_into"),
            reason=data.get("reason"),
        )
        for slot, data in payload.items()
    }


def resolve_slot(skyrim_slot: str | int, mappings: dict[str, CDSlotMapping] | None = None) -> CDSlotMapping:
    table = mappings or load_slot_mappings()
    key = str(skyrim_slot)
    if key in table:
        mapping = table[key]
        if mapping.status == "merge":
            warnings.warn(
                f"Skyrim slot {key} ({mapping.skyrim_name}) will merge into {mapping.merge_into}: {mapping.reason}",
                RuntimeWarning,
                stacklevel=2,
            )
        return mapping
    return CDSlotMapping(
        skyrim_slot=key,
        skyrim_name=f"Unknown-{key}",
        cd_slot_name=None,
        cd_hash=None,
        status="unsupported",
        reason="No mapping entry exists.",
    )


def build_mapping_report(skyrim_slots: list[str | int]) -> MappingReport:
    report = MappingReport()
    mappings = load_slot_mappings()
    for slot in skyrim_slots:
        report.add(resolve_slot(slot, mappings))
    return report


def _mapping_dict(mapping: CDSlotMapping) -> dict[str, str | None]:
    return {
        "skyrim_slot": mapping.skyrim_slot,
        "skyrim_name": mapping.skyrim_name,
        "cd_slot_name": mapping.cd_slot_name,
        "cd_hash": mapping.cd_hash,
        "status": mapping.status,
        "merge_into": mapping.merge_into,
        "reason": mapping.reason,
    }
