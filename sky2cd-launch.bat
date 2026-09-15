@echo off
rem Double-click launcher for dist\sky2cd.exe.
rem Keeps the console window open after the CLI exits so usage/errors are readable.
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\sky2cd.exe"

if not exist "%EXE%" (
    echo Could not find "%EXE%".
    echo Build it first with: build_exe.ps1
    pause
    exit /b 1
)

"%EXE%" %*
echo.
pause
