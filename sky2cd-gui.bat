@echo off
REM Optional launcher for the sky2cd desktop GUI.
REM The main deliverable is dist\sky2cd-gui.exe, which can be double-clicked
REM directly. This batch file only adds a visible error if the exe is missing.
setlocal
set "EXE=%~dp0dist\sky2cd-gui.exe"

if not exist "%EXE%" (
    echo Could not find "%EXE%".
    echo Build it first with:  powershell -ExecutionPolicy Bypass -File build_exe.ps1
    pause
    exit /b 1
)

start "" "%EXE%" %*
endlocal
