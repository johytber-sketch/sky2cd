<#
.SYNOPSIS
    Build a clean, GUI-only Nexus Mods upload ZIP from the current
    dist\sky2cd-gui.exe build.

.DESCRIPTION
    Packages only what a Nexus end user needs: the standalone GUI exe, a
    short plain-text README, the project LICENSE, and THIRD_PARTY_NOTICES.md.
    Deliberately excludes sky2cd.exe (CLI), source code, build artifacts,
    developer docs, and any game/mod assets.

    Requires dist\sky2cd-gui.exe to already exist (run build_exe.ps1 -Target
    gui first). Does not touch GitHub releases or tags.

.PARAMETER Version
    Version label used in the output filename, e.g. "v0.1.3-preview".
    Defaults to the most recent git tag description.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\package_nexus_zip.ps1
#>
param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$GuiExe = Join-Path $RepoRoot "dist\sky2cd-gui.exe"
if (-not (Test-Path $GuiExe)) {
    throw "dist\sky2cd-gui.exe not found. Build it first: powershell -File .\build_exe.ps1 -Target gui"
}

if (-not $Version) {
    $Version = (git describe --tags --abbrev=0 2>$null)
    if (-not $Version) { $Version = "v0.0.0" }
}

$CommitSha = (git rev-parse --short HEAD 2>$null)
if (-not $CommitSha) { $CommitSha = "unknown" }

$StagingDir = Join-Path $RepoRoot "build\nexus-staging"
if (Test-Path $StagingDir) { Remove-Item $StagingDir -Recurse -Force }
New-Item -ItemType Directory -Path $StagingDir | Out-Null

Copy-Item $GuiExe (Join-Path $StagingDir "sky2cd-gui.exe")
Copy-Item (Join-Path $RepoRoot "LICENSE") (Join-Path $StagingDir "LICENSE")
Copy-Item (Join-Path $RepoRoot "THIRD_PARTY_NOTICES.md") (Join-Path $StagingDir "THIRD_PARTY_NOTICES.md")

$ReadmeText = @"
Sky2Cd GUI - $Version (built from commit $CommitSha)
=====================================================

What this is
------------
Sky2Cd is a Blender preparation toolkit for artist-assisted Skyrim outfit
work. This package contains only the standalone graphical tool
(sky2cd-gui.exe). Its output is a preview/mockup for inspection and manual
work in Blender -- NOT a fitted, rigged, tested, or game-ready outfit.

Install
-------
1. Extract this ZIP anywhere (e.g. Desktop or Documents).
2. Double-click sky2cd-gui.exe to launch. No Python install is required --
   the exe bundles its own runtime and dependencies.

Windows may show a SmartScreen "Windows protected your PC" warning because
the exe is not code-signed. Click "More info" then "Run anyway" if you trust
the source you downloaded this from.

Requirements
------------
- Windows 10/11 (64-bit). No separate Python install needed.
- Blender is REQUIRED to actually open, inspect, and work with the preview
  files this tool produces. Blender is not bundled or installed by this exe.
- CrimsonForge and a real game install are OPTIONAL -- only needed if you use
  the live donor-verification / DMM packaging features. Most users doing
  Blender preview/prep work do not need them.

First launch
------------
The GUI opens with two tabs: "Blender Prep & Preview" (recommended starting
point) and an optional "Advanced DMM Packaging" tab. A Dark/Light mode
toggle is available and its choice is remembered for next time.

Basic workflow
--------------
1. Pick an input outfit file/archive and an output folder.
2. Click "Create Preview Files" to generate Blender-ready preview geometry
   and an import_script.py.
3. Open the output folder's import_script.py in Blender, then inspect, fit,
   clip, weight-paint, rig, and validate the result manually.
4. Optionally use "Suggest donor" for a ranked, human-readable starting
   recommendation -- this does not guarantee fit, clipping safety, rig
   correctness, animation safety, or a finished wearable conversion.

Limitations (read before using)
--------------------------------
- No automatic body fitting, clipping correction, or rig/weight transfer.
- No animation certification and no game-ready guarantee of any kind.
- Donor suggestions are starting points for artist review, not verified
  matches.
- Advanced DMM packaging performs structural/file-format checks only; this
  is not fit validation and does not certify a working in-game result.
- The artist remains responsible for fit, clipping, materials, rig/weights,
  rebuild/export, and in-game/animation testing.

Licensing note
--------------
This exe is distributed under the MIT license (see LICENSE). It bundles a
vendored NiflyDLL.dll component (used only for optional .nif import) derived
from the GPL-3.0-licensed PyNifly project. See THIRD_PARTY_NOTICES.md for
full attribution and an open compliance item: the exact PyNifly source
revision used to build the bundled DLL has not yet been recorded/verified
against GPL-3.0 source-availability requirements. Resolve this before
treating any published build as fully license-compliant.

Command-line version
---------------------
A command-line build (sky2cd.exe) also exists but is intentionally NOT
included in this Nexus package. It is published only via GitHub releases
for advanced/scripted use: https://github.com/johytber-sketch/sky2cd/releases
"@

Set-Content -Path (Join-Path $StagingDir "README.txt") -Value $ReadmeText -Encoding UTF8

$OutDir = Join-Path $RepoRoot "dist"
$ZipName = "Sky2Cd-$Version-Nexus-GUI.zip"
$ZipPath = Join-Path $OutDir $ZipName
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

Compress-Archive -Path (Join-Path $StagingDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal

$Hash = (Get-FileHash -Path $ZipPath -Algorithm SHA256).Hash
Write-Output "Built: $ZipPath"
Write-Output "SHA256: $Hash"
Write-Output "Contents:"
Get-ChildItem $StagingDir | ForEach-Object { Write-Output ("  {0,12} bytes  {1}" -f $_.Length, $_.Name) }
