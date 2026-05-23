@echo off
cd /d "%~dp0"

if not exist .venv (
    echo [Pochtalion] Virtual environment not found. Creating...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Python not found. Install Python 3.10+ from https://python.org and try again.
        pause
        exit /b 1
    )
    echo [Pochtalion] Installing dependencies...
    .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to install dependencies.
        pause
        exit /b 1
    )
)

if exist .venv\Scripts\pythonw.exe (
    start "" .venv\Scripts\pythonw.exe main.py
) else (
    .venv\Scripts\python.exe main.py
)
