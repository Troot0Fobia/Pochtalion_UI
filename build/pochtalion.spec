# PyInstaller recipe for Pochtalion.  -*- mode: python ; coding: utf-8 -*-
#
# Build with:  pyinstaller build/pochtalion.spec  (the build/ scripts do this
# with the deterministic environment set up — don't call it by hand for a real
# release).
#
# Output: dist/Pochtalion/  (onedir)
#     Pochtalion[.exe]          launcher
#     _internal/                Python, Qt, and the bundled resources below
#
# onedir, not onefile:
#   - QtWebEngine (a ~150 MB Chromium) is fragile and slow to unpack from a
#     onefile archive on every launch
#   - onefile executables draw more antivirus false positives
#   - a directory tree is far easier to make reproducible and to diff
#
# What goes in the bundle: ONLY read-only resources. Everything the app writes
# at runtime (database, settings.json, Telethon sessions, photos, logs) is
# resolved by core.paths to a per-user data directory and must never be here.

import re
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).parent

# --- version (config.py is the single source of truth) ------------------------
_config_text = (PROJECT_ROOT / "config.py").read_text(encoding="utf-8")
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', _config_text).group(1)

# --- read-only resources shipped with the app --------------------------------
# (src, dest-dir-inside-_internal); dest matches core.paths.RESOURCE_ROOT layout
datas = [
    (str(PROJECT_ROOT / "web"), "web"),
    (str(PROJECT_ROOT / "settings" / "defaults.json"), "settings"),
    (str(PROJECT_ROOT / "icon.ico"), "."),
]

# The app has no dynamic imports; PyInstaller's static analysis plus the
# bundled hooks (PyQt6/QtWebEngine) and hooks-contrib (puremagic, tzdata)
# cover the dependency set. Add here only if a build turns up a missing module.
hiddenimports = []

# Trim things we never use — smaller tree, fewer moving parts in the hash.
excludes = [
    "tkinter",
    "test",
    "unittest",
    "pydoc",
    "pip",
    "wheel",
    "setuptools",
]

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # onedir: binaries live in _internal/
    name="Pochtalion",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,                    # stripping varies by binutils version -> not reproducible
    upx=False,                      # UPX breaks reproducibility and trips antivirus
    console=False,                  # GUI app: no console window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Pochtalion",
)
