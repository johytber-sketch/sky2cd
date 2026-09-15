# Third-party notices and release blockers

## PyNifly

`src/sky2cd/vendor/io_scene_nifly/` contains portions of
[BadDogSkyrim/PyNifly](https://github.com/BadDogSkyrim/PyNifly), copyright
Bad Dog and contributors. The vendored addon reports version `28.3.0`.
PyNifly's upstream repository is licensed under the **GNU General Public
License, version 3 (`GPL-3.0-only`)**. A verbatim copy of the upstream license is included at
`src/sky2cd/vendor/io_scene_nifly/LICENSE`.

PyNifly is based on the Nifly layer from BodySlide/Outfit Studio and credits
Ousnius and additional contributors in its upstream README. This notice does
not assert licensing terms for those separately authored dependencies beyond
what PyNifly's upstream repository states.

### Public binary release blocker

The vendored Python sources checked during the 2026-09-15 audit match the
corresponding files on PyNifly's upstream default branch, but this checkout
does not record a source commit or release archive checksum. In addition,
`NiflyDLL.dll` has no embedded version or source-revision metadata. Before
publishing a Windows executable that contains that DLL, record the exact
PyNifly source revision and verify that the DLL was built from the
corresponding source, then satisfy GPL-3.0 source-availability requirements.

Local builds include only the runtime `pyn/` package, `NiflyDLL.dll`, this
notice, and the GPL-3.0 text. They intentionally exclude PyNifly's bundled
Bethesda-format skeleton NIFs, Blender asset file, editor marker, and
`hkxcmd.exe`; their separate redistribution provenance was not established by
this audit.

## CrimsonForge

CrimsonForge is not vendored. Optional live donor inspection loads a separate
user-installed copy from
[hzeemr/crimsonforge](https://github.com/hzeemr/crimsonforge). Its repository
identifies the project as MIT licensed. No CrimsonForge code or game assets are
included in Sky2Cd distributions.

## User-provided assets

Sky2Cd does not grant rights to Skyrim, Crimson Desert, or third-party mod
assets. Documentation examples use placeholders only. Users must supply their
own lawfully obtained files and must review the permissions for every source
asset and resulting work.
