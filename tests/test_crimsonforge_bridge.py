"""Unit tests for `sky2cd.crimsonforge_bridge` (locating/using a real, separate
CrimsonForge install -- never bundled/vendored, see module docstring).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sky2cd.crimsonforge_bridge import (
    CrimsonForgeNotFoundError,
    find_crimsonforge_home,
    find_donor_entry,
    find_sidecar_files,
    load_crimsonforge_modules,
    read_donor_pac_bytes,
    read_sidecar_files,
)


def _make_fake_crimsonforge_home(tmp_path: Path) -> Path:
    home = tmp_path / "FakeCrimsonForge"
    core_dir = home / "core"
    core_dir.mkdir(parents=True)
    (core_dir / "__init__.py").write_text("", encoding="utf-8")
    (core_dir / "mesh_importer.py").write_text(
        "def import_obj(path):\n    return {'path': path}\n\n"
        "def build_pac(mesh, original_data):\n    return b'REBUILT:' + original_data\n",
        encoding="utf-8",
    )
    (core_dir / "mesh_exporter.py").write_text(
        "def export_obj(mesh, output_dir, name=''):\n"
        "    import os\n"
        "    with open(os.path.join(output_dir, name + '.obj'), 'w') as f:\n"
        "        f.write('# fake obj\\n')\n",
        encoding="utf-8",
    )
    (core_dir / "mesh_parser.py").write_text(
        "def parse_mesh(data, filename=''):\n    return {'data': data, 'filename': filename}\n",
        encoding="utf-8",
    )
    (core_dir / "vfs_manager.py").write_text(
        "class VfsManager:\n"
        "    def __init__(self, packages_path):\n"
        "        self.packages_path = packages_path\n",
        encoding="utf-8",
    )
    return home


def test_find_crimsonforge_home_via_explicit_path(tmp_path):
    home = _make_fake_crimsonforge_home(tmp_path)
    found = find_crimsonforge_home(explicit=home)
    assert found == home


def test_find_crimsonforge_home_via_env_var(tmp_path, monkeypatch):
    home = _make_fake_crimsonforge_home(tmp_path)
    monkeypatch.setenv("CRIMSONFORGE_HOME", str(home))
    found = find_crimsonforge_home()
    assert found == home


def test_find_crimsonforge_home_returns_none_when_not_found(tmp_path, monkeypatch):
    monkeypatch.delenv("CRIMSONFORGE_HOME", raising=False)
    # Isolate from this machine's real CrimsonForge install (this environment
    # genuinely has one) by pointing the common-install-hint search at an
    # empty fake home directory instead.
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fake_home")
    found = find_crimsonforge_home(explicit=tmp_path / "nonexistent")
    assert found is None


def test_load_crimsonforge_modules_raises_when_missing(tmp_path):
    with pytest.raises(CrimsonForgeNotFoundError):
        load_crimsonforge_modules(tmp_path / "nonexistent")


def test_load_crimsonforge_modules_imports_real_looking_modules(tmp_path):
    home = _make_fake_crimsonforge_home(tmp_path)
    cf = load_crimsonforge_modules(home)
    assert cf.mesh_importer.import_obj("x") == {"path": "x"}
    assert cf.mesh_importer.build_pac(None, b"ORIG") == b"REBUILT:ORIG"


class _FakeEntry:
    def __init__(self, path: str, data: bytes):
        self.path = path
        self._data = data


class _FakeVfs:
    def __init__(self, groups: dict[str, list[_FakeEntry]]):
        self._groups = groups

    def list_package_groups(self):
        return list(self._groups)

    def load_pamt(self, group):
        class _Pamt:
            def __init__(self, entries):
                self.file_entries = entries

        return _Pamt(self._groups[group])

    def read_entry_data(self, entry):
        return entry._data


def test_find_donor_entry_searches_hinted_group_first():
    vfs = _FakeVfs({"0009": [_FakeEntry("character/x.pac", b"XDATA")]})
    group, entry = find_donor_entry(vfs, "character/x.pac", package_group_hint="0009")
    assert group == "0009"
    assert entry.path == "character/x.pac"


def test_find_donor_entry_scans_all_groups_without_hint():
    vfs = _FakeVfs({"0001": [], "0009": [_FakeEntry("character/x.pac", b"XDATA")]})
    group, entry = find_donor_entry(vfs, "character/x.pac")
    assert group == "0009"


def test_find_donor_entry_raises_filenotfound_when_missing():
    vfs = _FakeVfs({"0009": [_FakeEntry("character/other.pac", b"X")]})
    with pytest.raises(FileNotFoundError):
        find_donor_entry(vfs, "character/x.pac")


def test_read_donor_pac_bytes_returns_real_bytes():
    vfs = _FakeVfs({"0009": [_FakeEntry("character/x.pac", b"XDATA")]})
    data = read_donor_pac_bytes(vfs, "character/x.pac", "0009")
    assert data == b"XDATA"


def test_find_sidecar_files_finds_pac_xml_and_textures():
    vfs = _FakeVfs(
        {
            "0009": [
                _FakeEntry("character/cd_phw_00_lb_00_0182.pac", b"PAC"),
                _FakeEntry("character/cd_phw_00_lb_00_0182.pac_xml", b"XML"),
                _FakeEntry("character/cd_phw_00_lb_00_0182_n.dds", b"NORMAL"),
                _FakeEntry("character/cd_phw_00_lb_00_0182_disp.dds", b"DISP"),
                _FakeEntry("character/cd_phw_00_lb_00_0182_ma.dds", b"MA"),
                _FakeEntry("character/cd_phw_00_lb_00_0182_mg.dds", b"MG"),
                # Should be excluded: a real physics file (reference mods don't ship it)...
                _FakeEntry("character/cd_phw_00_lb_00_0182.hkx", b"HKX"),
                # ...and a genuinely unrelated item's texture (different item number).
                _FakeEntry("character/cd_phw_00_lb_00_9999_n.dds", b"UNRELATED"),
            ]
        }
    )
    sidecars = find_sidecar_files(vfs, "character/cd_phw_00_lb_00_0182.pac", "0009")
    paths = sorted(e.path for e in sidecars)
    assert paths == [
        "character/cd_phw_00_lb_00_0182.pac_xml",
        "character/cd_phw_00_lb_00_0182_disp.dds",
        "character/cd_phw_00_lb_00_0182_ma.dds",
        "character/cd_phw_00_lb_00_0182_mg.dds",
        "character/cd_phw_00_lb_00_0182_n.dds",
    ]


def test_find_sidecar_files_returns_empty_when_none_exist():
    vfs = _FakeVfs({"0009": [_FakeEntry("character/cd_phw_00_lb_00_0182.pac", b"PAC")]})
    assert find_sidecar_files(vfs, "character/cd_phw_00_lb_00_0182.pac", "0009") == []


def test_read_sidecar_files_returns_real_bytes_by_path():
    vfs = _FakeVfs(
        {
            "0009": [
                _FakeEntry("character/cd_phw_00_lb_00_0182.pac", b"PAC"),
                _FakeEntry("character/cd_phw_00_lb_00_0182.pac_xml", b"XML"),
                _FakeEntry("character/cd_phw_00_lb_00_0182_n.dds", b"NORMAL"),
            ]
        }
    )
    sidecar_bytes = read_sidecar_files(vfs, "character/cd_phw_00_lb_00_0182.pac", "0009")
    assert sidecar_bytes == {
        "character/cd_phw_00_lb_00_0182.pac_xml": b"XML",
        "character/cd_phw_00_lb_00_0182_n.dds": b"NORMAL",
    }
