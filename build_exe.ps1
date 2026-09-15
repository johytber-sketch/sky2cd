param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [ValidateSet("all", "cli", "gui")]
    [string]$Target = "all"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonPath = Join-Path $Root $Python
if (-not (Test-Path $PythonPath)) {
    throw "Python environment not found at $PythonPath. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e `".[dev,build]`""
}

$DataSource = Join-Path $Root "src\sky2cd\data"
$DataTarget = "sky2cd\data"
$VendorRoot = Join-Path $Root "src\sky2cd\vendor\io_scene_nifly"
$VendorPynSource = Join-Path $VendorRoot "pyn"
$VendorPynTarget = "sky2cd\vendor\io_scene_nifly\pyn"
$VendorDllSource = Join-Path $VendorRoot "NiflyDLL.dll"
$VendorDllTarget = "sky2cd\vendor\io_scene_nifly"
$VendorLicenseSource = Join-Path $VendorRoot "LICENSE"
$VendorLicenseTarget = "sky2cd\vendor\io_scene_nifly"
$NoticesSource = Join-Path $Root "THIRD_PARTY_NOTICES.md"
$CliSource = Join-Path $Root "src\sky2cd\cli.py"
$GuiSource = Join-Path $Root "src\sky2cd\gui.py"
$SrcPath = Join-Path $Root "src"
$SpecPath = Join-Path $Root "build\pyinstaller"
$CliWorkPath = Join-Path $Root "build\pyinstaller\work-cli"
$GuiWorkPath = Join-Path $Root "build\pyinstaller\work-gui"
$DistPath = Join-Path $Root "dist"

if ($Target -eq "all" -or $Target -eq "cli") {
    & $PythonPath -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --console `
        --name sky2cd `
        --paths $SrcPath `
        --add-data "$DataSource;$DataTarget" `
        --add-data "$VendorPynSource;$VendorPynTarget" `
        --add-data "$VendorLicenseSource;$VendorLicenseTarget" `
        --add-data "$NoticesSource;." `
        --add-binary "$VendorDllSource;$VendorDllTarget" `
        --exclude-module bpy `
        --hidden-import lz4.block `
        --hidden-import cryptography.hazmat.primitives.ciphers `
        --hidden-import cryptography.hazmat.backends.openssl `
        --hidden-import cffi `
        --collect-all fast_simplification `
        --collect-all PIL `
        --distpath $DistPath `
        --workpath $CliWorkPath `
        --specpath $SpecPath `
        $CliSource
    if ($LASTEXITCODE -ne 0) { throw "CLI build failed with exit code $LASTEXITCODE" }
    Write-Host "Built $DistPath\sky2cd.exe"
}

if ($Target -eq "all" -or $Target -eq "gui") {
    # --windowed produces a GUI-subsystem exe: double-clicking it shows the
    # tkinter window with no console window behind it.
    & $PythonPath -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name sky2cd-gui `
        --paths $SrcPath `
        --add-data "$DataSource;$DataTarget" `
        --add-data "$VendorPynSource;$VendorPynTarget" `
        --add-data "$VendorLicenseSource;$VendorLicenseTarget" `
        --add-data "$NoticesSource;." `
        --add-binary "$VendorDllSource;$VendorDllTarget" `
        --hidden-import tkinter `
        --hidden-import tkinter.ttk `
        --hidden-import tkinter.filedialog `
        --hidden-import tkinter.messagebox `
        --hidden-import windnd `
        --hidden-import sky2cd.pipeline `
        --hidden-import lz4.block `
        --hidden-import cryptography.hazmat.primitives.ciphers `
        --hidden-import cryptography.hazmat.backends.openssl `
        --hidden-import cffi `
        --exclude-module bpy `
        --collect-all fast_simplification `
        --collect-all PIL `
        --distpath $DistPath `
        --workpath $GuiWorkPath `
        --specpath $SpecPath `
        $GuiSource
    if ($LASTEXITCODE -ne 0) { throw "GUI build failed with exit code $LASTEXITCODE" }
    Write-Host "Built $DistPath\sky2cd-gui.exe"
}
