"""Automates the "run CrimsonForge by hand" step of the replacer workflow.

**Why this exists:** the remaining manual steps in the sky2cd pipeline were,
until now, "open CrimsonForge's own GUI, export the donor to OBJ, then import
the merged OBJ and patch/rebuild the .pac." CrimsonForge (MIT licensed --
verified via its real `LICENSE` file) exposes all of that as plain importable
Python functions in its `core` package: `core.mesh_parser.parse_mesh` (bytes
-> mesh), `core.mesh_exporter.export_obj` (mesh -> donor .obj), and
`core.mesh_importer.import_obj` / `build_pac` (merged .obj + original donor
bytes -> rebuilt .pac bytes). This module calls those functions directly, so
the whole donor-export + rebuild step can run unattended from `sky2cd`
without the user ever opening CrimsonForge's own UI.

**We do not vendor/ship CrimsonForge's code.** Its MIT license permits that,
but the actual mesh-editing logic is substantial, third-party maintained
software; bundling a copy would mean carrying a stale fork forever. Instead,
this module expects a **separate, one-time CrimsonForge install** (the user
already has one) and locates it (by explicit path, `CRIMSONFORGE_HOME` env
var, saved user setting, or a short list of common install locations), then
imports its modules live off disk -- the same "point us at your existing
install" pattern Skyrim tooling like FNIS/BodySlide already uses.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

__all__ = [
    "CrimsonForgeNotFoundError",
    "find_crimsonforge_home",
    "find_packages_path",
    "load_crimsonforge_modules",
    "open_vfs",
    "find_donor_entry",
    "read_donor_pac_bytes",
    "export_donor_obj",
    "rebuild_pac",
    "find_sidecar_files",
    "read_sidecar_files",
    "ItemNameResolver",
    "build_item_name_resolver",
]

_COMMON_INSTALL_HINTS = (
    "Desktop/CrimsonForge",
    "Desktop/crimsonforge",
    "CrimsonForge",
    "AppData/Local/CrimsonForge",
    "source/repos/crimsonforge_src/CrimsonForge",
)

_COMMON_PACKAGES_HINTS = (
    "C:/Program Files (x86)/Steam/steamapps/common/Crimson Desert/packages",
    "C:/Program Files/Steam/steamapps/common/Crimson Desert/packages",
    "D:/SteamLibrary/steamapps/common/Crimson Desert/packages",
    "E:/SteamLibrary/steamapps/common/Crimson Desert/packages",
    "F:/SteamLibrary/steamapps/common/Crimson Desert/packages",
    "G:/SteamLibrary/steamapps/common/Crimson Desert/packages",
    "C:/SteamLibrary/steamapps/common/Crimson Desert/packages",
    "D:/Crimson Desert/packages",
    "E:/Crimson Desert/packages",
    "C:/Crimson Desert/packages",
)


def find_packages_path(explicit: str | Path | None = None) -> Path | None:
    """Locate the real Crimson Desert game's packages/ directory.

    Resolution order: `explicit` argument, `CRIMSON_DESERT_PACKAGES` environment
    variable, then common Steam and game install paths.
    """
    if explicit:
        p = Path(explicit)
        if p.is_dir():
            return p
    env_val = os.environ.get("CRIMSON_DESERT_PACKAGES") or os.environ.get("CRIMSONDESERT_PACKAGES")
    if env_val:
        p = Path(env_val)
        if p.is_dir():
            return p
    for hint in _COMMON_PACKAGES_HINTS:
        p = Path(hint)
        if p.is_dir():
            return p
    return None

_MARKER_RELATIVE_FILE = Path("core") / "mesh_importer.py"


class CrimsonForgeNotFoundError(RuntimeError):
    """Raised when no usable CrimsonForge install can be located."""


def _looks_like_crimsonforge_home(path: Path) -> bool:
    return (path / _MARKER_RELATIVE_FILE).is_file()


def find_crimsonforge_home(explicit: str | Path | None = None) -> Path | None:
    """Locate a CrimsonForge install's Python source root.

    Resolution order: `explicit` argument, `CRIMSONFORGE_HOME` environment
    variable, then a short list of common install locations under the user's
    home directory. Returns `None` if none of them contain a real
    `core/mesh_importer.py` (i.e. nothing usable was found).
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_value = os.environ.get("CRIMSONFORGE_HOME")
    if env_value:
        candidates.append(Path(env_value))
    home = Path.home()
    for hint in _COMMON_INSTALL_HINTS:
        candidates.append(home / hint)

    for candidate in candidates:
        if _looks_like_crimsonforge_home(candidate):
            return candidate
    return None


def load_crimsonforge_modules(crimsonforge_home: str | Path) -> types.SimpleNamespace:
    """Import CrimsonForge's `core` package modules live from `crimsonforge_home`.

    Returns a namespace with `mesh_parser`, `mesh_exporter`, `mesh_importer`,
    and `vfs_manager` attributes bound to the real imported modules.

    Raises:
        CrimsonForgeNotFoundError: if `crimsonforge_home` doesn't contain a
            real CrimsonForge `core` package.
    """
    home = Path(crimsonforge_home)
    if not _looks_like_crimsonforge_home(home):
        raise CrimsonForgeNotFoundError(
            f"'{home}' does not look like a CrimsonForge install "
            f"(missing {_MARKER_RELATIVE_FILE})"
        )

    home_str = str(home)
    if home_str not in sys.path:
        sys.path.insert(0, home_str)

    import importlib

    mesh_parser = importlib.import_module("core.mesh_parser")
    mesh_exporter = importlib.import_module("core.mesh_exporter")
    mesh_importer = importlib.import_module("core.mesh_importer")
    vfs_manager = importlib.import_module("core.vfs_manager")

    return types.SimpleNamespace(
        mesh_parser=mesh_parser,
        mesh_exporter=mesh_exporter,
        mesh_importer=mesh_importer,
        vfs_manager=vfs_manager,
        home=home,
    )


def open_vfs(cf, packages_path: str | Path):
    """Open the real game's packages/ directory via CrimsonForge's own VfsManager.

    `cf` is the namespace returned by `load_crimsonforge_modules`.
    """
    return cf.vfs_manager.VfsManager(str(packages_path))


def find_donor_entry(vfs, entry_path: str, package_group_hint: str = ""):
    """Find a real file entry by its VFS-relative path (e.g. 'character/x.pac').

    Searches `package_group_hint` first (if given), then every package group
    reported by `vfs.list_package_groups()`. Returns `(group_dir, entry)` or
    raises `FileNotFoundError` if no group contains a matching entry.
    """
    normalized = entry_path.replace("\\", "/").lower()
    groups = [package_group_hint] if package_group_hint else []
    groups += [g for g in vfs.list_package_groups() if g not in groups]

    for group in groups:
        if not group:
            continue
        try:
            pamt = vfs.load_pamt(group)
        except Exception:
            continue
        for entry in pamt.file_entries:
            if entry.path.replace("\\", "/").lower() == normalized:
                return group, entry
    raise FileNotFoundError(f"No package group contains entry path '{entry_path}'")


def read_donor_pac_bytes(vfs, entry_path: str, package_group_hint: str = "") -> bytes:
    """Read a real donor .pac's bytes straight out of the live game install."""
    _, entry = find_donor_entry(vfs, entry_path, package_group_hint)
    return vfs.read_entry_data(entry)


def find_sidecar_files(vfs, entry_path: str, package_group_hint: str = ""):
    """Find a donor .pac's real sidecar files (material XML + textures).

    **Why this exists:** a real, confirmed-working DMM mod ("Proxima Shell Mesh
    Mod", generated by CrimsonForge and inspected directly on the user's live
    DMM install) ships more than just the `.pac` for every item it replaces --
    it also ships that item's real `.pac_xml` (submesh->material bindings,
    texture paths, tint/grime parameters) and every `_n`/`_disp`/`_ma`/`_mg.dds`
    texture the `.pac_xml` references. A package with only the `.pac` (what
    `sky2cd` shipped before this) is missing those, which is the most likely
    reason an earlier real test mod didn't work in-game.

    A sidecar is any file in the same VFS package group whose name is either
    exactly `<donor-basename>.pac_xml`, or `<donor-basename>_<suffix>.dds`
    (covers `_n`, `_disp`, `_ma`, `_mg`, and any other real texture-channel
    suffix without hardcoding a fixed list). Real `.hkx` physics files are
    intentionally excluded -- the reference mod doesn't ship them either, and
    `sky2cd`'s donor merge never touches physics/collision data.

    Returns a list of real VFS file-entry objects (same type `find_donor_entry`
    returns), each with a `.path` attribute; pass them to
    `vfs.read_entry_data(entry)` (or use `read_sidecar_files` to do that for
    every entry at once).
    """
    group, _ = find_donor_entry(vfs, entry_path, package_group_hint)
    stem = Path(entry_path).stem
    pamt = vfs.load_pamt(group)
    sidecars = []
    for entry in pamt.file_entries:
        name = Path(entry.path).name
        if name == f"{stem}.pac_xml" or (name.startswith(f"{stem}_") and name.lower().endswith(".dds")):
            sidecars.append(entry)
    return sidecars


def read_sidecar_files(vfs, entry_path: str, package_group_hint: str = "") -> dict[str, bytes]:
    """Read every real sidecar file's bytes for a donor `.pac` (see `find_sidecar_files`).

    Returns a `{vfs_path: bytes}` dict, e.g.
    `{"character/cd_phw_00_lb_00_0182.pac_xml": b"...", "character/cd_phw_00_lb_00_0182_n.dds": b"..."}`.
    """
    entries = find_sidecar_files(vfs, entry_path, package_group_hint)
    return {entry.path: vfs.read_entry_data(entry) for entry in entries}


def export_donor_obj(cf, pac_bytes: bytes, entry_path: str, out_dir: str | Path) -> Path:
    """Parse a real donor .pac's bytes and export it to .obj via CrimsonForge.

    `cf` is the namespace returned by `load_crimsonforge_modules`. Returns
    the path to the written .obj.
    """
    name = Path(entry_path).stem
    mesh = cf.mesh_parser.parse_mesh(pac_bytes, filename=entry_path)
    cf.mesh_exporter.export_obj(mesh, str(out_dir), name=name)
    obj_path = Path(out_dir) / f"{name}.obj"
    if not obj_path.is_file():
        raise RuntimeError(f"CrimsonForge export_obj did not produce expected file: {obj_path}")
    return obj_path


class ItemNameResolver:
    """Resolves a donor `.pac` entry path to its real in-game display name.

    **Why this exists:** CrimsonForge's own `core.item_catalog`/`core.item_index`
    name-resolution code is written against an older game build -- it looks for
    `gamedata/iteminfo.pabgb` and `gamedata/localizationstring_eng`, but on the
    2.02.00 build those files are actually named `gamedata/iteminfo.staticinfobody`
    and `gamedata/item.paloc` respectively, so `build_item_catalog`/
    `build_item_index` silently return zero items on this build. This class
    re-derives the same information directly: for a target prefab base name
    (e.g. `cd_phw_00_foot_00_0163`, derived from the `.pac` path), it hashes a
    handful of common suffix variants with the same `hashlittle(name, 0xC5EDE)`
    used by CrimsonForge's hash table, searches for that raw hash's bytes
    inside `iteminfo.staticinfobody` directly (skipping the offset-based
    record walk that no longer matches this build's byte layout), then walks
    backward to the nearest preceding item-name marker to recover the item's
    numeric ID, and finally looks that ID up in `item.paloc`'s
    `(item_id << 32) | 0x70` localized-name entries.

    Not every donor resolves to a name -- some real, in-game usable meshes
    (confirmed by manual testing) are NPC-exclusive prefabs with no player
    item record at all; `resolve()` returns `None` for those rather than
    guessing.
    """

    _SUFFIXES = ("", "_l", "_r", "_u", "_s", "_t", "_index01", "_index02", "_index03")

    def __init__(self, hashlittle, iteminfo_marker, iteminfo_data: bytes, name_by_key: dict[int, str]):
        self._hashlittle = hashlittle
        self._marker = iteminfo_marker
        self._data = iteminfo_data
        self._name_by_key = name_by_key
        self._cache: dict[str, str | None] = {}

    def _name_at(self, pos: int):
        import re
        import struct

        data = self._data
        marker_pos = data.rfind(self._marker, 0, pos)
        if marker_pos == -1:
            return None
        name_start = marker_pos
        while name_start > 0 and 0x21 <= data[name_start - 1] <= 0x7E:
            name_start -= 1
            if marker_pos - name_start > 150:
                break
        if marker_pos - name_start < 3 or name_start < 8:
            return None
        internal_name = data[name_start:marker_pos].decode("ascii", errors="replace")
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", internal_name):
            return None
        name_len = struct.unpack_from("<I", data, name_start - 4)[0]
        item_id = struct.unpack_from("<I", data, name_start - 8)[0]
        if name_len not in (len(internal_name), len(internal_name) + 1):
            return None
        if item_id < 100 or item_id > 100_000_000:
            return None
        return item_id

    def resolve_base(self, base_name: str) -> str | None:
        """Resolve a prefab base name (no directory, no `.pac` extension)."""
        import struct

        if base_name in self._cache:
            return self._cache[base_name]
        result = None
        for suffix in self._SUFFIXES:
            digest = self._hashlittle((base_name + suffix).encode("ascii"), 0xC5EDE)
            pos = self._data.find(struct.pack("<I", digest))
            if pos == -1:
                continue
            item_id = self._name_at(pos)
            if item_id is None:
                continue
            display = self._name_by_key.get((item_id << 32) | 0x70)
            if display:
                result = display
                break
        self._cache[base_name] = result
        return result

    def resolve(self, entry_path: str) -> str | None:
        """Resolve a donor `.pac` VFS entry path (e.g. `character/cd_phw_00_foot_00_0163.pac`)."""
        return self.resolve_base(Path(entry_path).stem)


def build_item_name_resolver(cf, vfs) -> ItemNameResolver:
    """Build an `ItemNameResolver` from a live game VFS.

    `cf` is the namespace from `load_crimsonforge_modules` (used only for its
    `.home` path, to import a couple more `core` modules on demand). Reads
    `gamedata/item.paloc` (group `0020`) and `gamedata/iteminfo.staticinfobody`
    (group `0008`) once; reuse the returned resolver across many `resolve()`
    calls rather than rebuilding it per donor.
    """
    import importlib

    home_str = str(cf.home)
    if home_str not in sys.path:
        sys.path.insert(0, home_str)
    crypto_engine = importlib.import_module("core.crypto_engine")
    item_catalog = importlib.import_module("core.item_catalog")
    paloc_parser = importlib.import_module("core.paloc_parser")

    pamt20 = vfs.load_pamt("0020")
    item_paloc_entry = next(e for e in pamt20.file_entries if e.path == "gamedata/item.paloc")
    paloc_entries = paloc_parser.parse_paloc(vfs.read_entry_data(item_paloc_entry))
    name_by_key = {int(e.key): e.value for e in paloc_entries if str(e.key).lstrip("-").isdigit()}

    pamt8 = vfs.load_pamt("0008")
    item_entry = next(e for e in pamt8.file_entries if e.path == "gamedata/iteminfo.staticinfobody")
    iteminfo_data = vfs.read_entry_data(item_entry)

    return ItemNameResolver(
        hashlittle=crypto_engine.hashlittle,
        iteminfo_marker=item_catalog.ITEMINFO_MARKER,
        iteminfo_data=iteminfo_data,
        name_by_key=name_by_key,
    )


_PAC_MAX_VERTICES_PER_SUBMESH = 65535  # real, confirmed format limit: submesh vertex counts are
# packed as unsigned 16-bit fields in CrimsonForge's PAC rebuild path. Hit live
# while testing a 51,767-vert donor + a larger outfit merged into one submesh
# (120,641 total verts) -- CrimsonForge's own `build_pac` raised
# `struct.error: 'H' format requires 0 <= number <= 65535` deep in
# `_build_pac_full_rebuild`. We check for this up front so callers get a
# clear, actionable message instead of that cryptic traceback.


def rebuild_pac(cf, merged_obj_path: str | Path, original_pac_bytes: bytes) -> bytes:
    """Rebuild a real, loadable .pac from a merged .obj via CrimsonForge.

    This automates the manual "Import + Patch to Game" action: imports the
    merged .obj (CrimsonForge infers bone weights for any new geometry from
    the nearest original donor vertex when no `.cfmeta.json` sidecar is
    present), then rebuilds it against `original_pac_bytes`.

    Raises:
        ValueError: if any submesh in the merged mesh exceeds the PAC
            format's real 65,535-vertex-per-submesh limit (confirmed by a
            live crash in CrimsonForge's own rebuild path) -- split the
            outfit across multiple submeshes, reduce its poly count, or pick
            a lower-vertex-count donor to resolve this.
    """
    mesh = cf.mesh_importer.import_obj(str(merged_obj_path))
    for submesh in getattr(mesh, "submeshes", []) or []:
        vertex_count = getattr(submesh, "vertex_count", 0) or len(getattr(submesh, "vertices", []))
        if vertex_count > _PAC_MAX_VERTICES_PER_SUBMESH:
            raise ValueError(
                f"Merged submesh has {vertex_count} vertices, exceeding the real PAC format's "
                f"{_PAC_MAX_VERTICES_PER_SUBMESH}-vertex-per-submesh limit (confirmed via a real "
                "CrimsonForge build_pac() crash: struct.error: 'H' format requires 0 <= number <= "
                "65535). Reduce the outfit's poly count, split it across more of the donor's "
                "existing submeshes (see sky2cd.donor_merge's submesh_strategy), or pick a "
                "lower-vertex-count donor."
            )
    return cf.mesh_importer.build_pac(mesh, original_pac_bytes)
