@echo off
REM Dev launcher (Windows). Creates a .venv on the exact pinned Python and
REM installs the hash-locked dependencies, then runs the app.
REM
REM The dev environment is deliberately identical to the build environment:
REM same Python (build\PYTHON_VERSION), same locked deps (requirements-windows.txt).

setlocal
cd /d "%~dp0"

set /p PYTHON_VERSION=<build\PYTHON_VERSION
set LOCK=requirements-windows.txt
REM Never silently substitute a Python already on this machine for the
REM pinned python-build-standalone build uv itself manages (see
REM build/build-windows.ps1 for why this matters).
set UV_PYTHON_PREFERENCE=only-managed

where uv >nul 2>nul
if errorlevel 1 (
    echo [Pochtalion] 'uv' is required. Install it with:
    echo     powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    echo   then re-run this script.
    exit /b 1
)

REM Recreate the venv if it is missing or on the wrong Python version.
set NEED_SETUP=1
if exist .venv\Scripts\python.exe (
    for /f %%v in ('.venv\Scripts\python.exe -c "import platform; print(platform.python_version())" 2^>nul') do (
        if "%%v"=="%PYTHON_VERSION%" set NEED_SETUP=0
    )
)
if "%NEED_SETUP%"=="1" (
    echo [Pochtalion] Creating .venv on Python %PYTHON_VERSION% ...
    if exist .venv rmdir /s /q .venv
    uv venv --python %PYTHON_VERSION% .venv
    if errorlevel 1 exit /b 1
)

REM Make the venv match the lock exactly (fast no-op when already in sync).
uv pip sync --python .venv --require-hashes %LOCK%
if errorlevel 1 exit /b 1

if exist .venv\Scripts\pythonw.exe (
    start "" .venv\Scripts\pythonw.exe main.py
) else (
    .venv\Scripts\python.exe main.py
)
