"""Unit tests for `sky2cd.donor_catalog` (metadata-only donor catalog)."""

from __future__ import annotations

import pytest

from sky2cd.donor_catalog import (
    BUILTIN_DONOR_CATALOG,
    DonorEntry,
    get_entry,
    list_catalog,
    verify_against_install,
)


def test_builtin_catalog_has_no_bundled_mesh_bytes():
    # The catalog is metadata-only: every entry is a plain string/bool/dataclass
    # field, never raw mesh/texture bytes (which would be Pearl Abyss's own
    # copyrighted assets).
    for entry in BUILTIN_DONOR_CATALOG:
        assert isinstance(entry.entry_path, str)
        assert entry.entry_path.endswith(".pac")
        assert "/" in entry.entry_path
        assert not entry.entry_path.startswith("/")


def test_list_catalog_returns_a_copy():
    first = list_catalog()
    second = list_catalog()
    assert first == second
    assert first is not second


def test_get_entry_found():
    entry = get_entry("demenissian_elite_leather_lb")
    assert entry.slot == "lowerbody"
    assert entry.entry_path == "character/cd_phw_00_lb_00_0182.pac"


def test_get_entry_missing_raises_keyerror():
    with pytest.raises(KeyError):
        get_entry("does_not_exist")


class _FakeEntry:
    def __init__(self, path: str):
        self.path = path


class _FakeVfs:
    """Fake VfsManager-like object for verify_against_install tests."""

    def __init__(self, groups: dict[str, list[str]]):
        self._groups = groups

    def list_package_groups(self):
        return list(self._groups)

    def load_pamt(self, group):
        class _Pamt:
            def __init__(self, paths):
                self.file_entries = [_FakeEntry(p) for p in paths]

        if group not in self._groups:
            raise FileNotFoundError(group)
        return _Pamt(self._groups[group])


def test_verify_against_install_reports_found_and_missing():
    vfs = _FakeVfs({"0009": ["character/cd_phw_00_lb_00_0182.pac"]})
    entries = [
        DonorEntry(id="a", display_name="A", slot="lowerbody", entry_path="character/cd_phw_00_lb_00_0182.pac", package_group="0009"),
        DonorEntry(id="b", display_name="B", slot="upperbody", entry_path="character/does_not_exist.pac"),
    ]
    results = verify_against_install(vfs, entries)
    assert results[0].found is True
    assert results[0].resolved_package_group == "0009"
    assert results[1].found is False
    assert "does_not_exist" in results[1].error
