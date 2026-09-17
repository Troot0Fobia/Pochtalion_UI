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

import os
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).parent

# --- version (VERSION file is the single source of truth) ---------------------
VERSION = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()

# --- self-update target repo, baked in from an env var, never hardcoded -------
# POCHTALION_UPDATE_REPO, set explicitly by whoever invokes the build (there is
# no default anywhere in this repo - see build/README.md "Enabling self-update
# checks"), is written into a gitignored REPO file that core.paths.REPO reads
# back at runtime. Left unset -> empty file -> modules.updater treats update
# checking as disabled. This is the only place the value gets written; it is
# never a literal in any .py source file.
(PROJECT_ROOT / "REPO").write_text(os.environ.get("POCHTALION_UPDATE_REPO", ""), encoding="utf-8")

# --- read-only resources shipped with the app --------------------------------
# (src, dest-dir-inside-_internal); dest matches core.paths.RESOURCE_ROOT layout
#
# pochtalion.ico is bundled unconditionally - core.paths.ICON points at it and
# ui/pochtalion_ui.py loads it via QIcon() at runtime for the window/taskbar
# icon. VERSION and REPO are bundled the same way - core.paths.VERSION /
# core.paths.REPO read them back. build/scripts/ holds the detached
# self-update helper (apply_update.sh / .ps1) as real, reviewable files
# rather than a string generated at update time - core.paths.UPDATE_HELPER
# resolves the one for the current platform. (Not the top-level scripts/ -
# that one holds unrelated desktop-integration/maintenance tools.)
datas = [
    (str(PROJECT_ROOT / "web"), "web"),
    (str(PROJECT_ROOT / "settings" / "defaults.json"), "settings"),
    (str(PROJECT_ROOT / "pochtalion.ico"), "."),
    (str(PROJECT_ROOT / "VERSION"), "."),
    (str(PROJECT_ROOT / "REPO"), "."),
    (str(PROJECT_ROOT / "build" / "scripts" / "apply_update.sh"), "scripts"),
    (str(PROJECT_ROOT / "build" / "scripts" / "apply_update.ps1"), "scripts"),
]

# PyInstaller's icon= (EXE-resource icon embedding, Windows/macOS only) is a
# SEPARATE, stricter use of the same file than the runtime taskbar icon
# above: it requires a real ICO container and can fail the build outright
# over a bad one on Windows rather than just warn (Linux ignores icon=
# entirely). Check the magic bytes and only pass icon= if it's a real ICO,
# so a Windows build still succeeds (unbranded .exe icon) if it ever isn't -
# the runtime taskbar icon is unaffected either way.
_icon_path = PROJECT_ROOT / "pochtalion.ico"
_icon_is_valid_ico = _icon_path.exists() and _icon_path.read_bytes()[:4] == b"\x00\x00\x01\x00"
if not _icon_is_valid_ico:
    print(f"WARNING: {_icon_path} is not a valid ICO file - building the .exe without an embedded icon resource")

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

# libgbm.so.1 gets auto-collected as a transitive dependency of Qt's Wayland
# platform plugin, pulled from whatever Mesa happens to be in the *build*
# container (Debian bookworm-slim) - but GBM is tightly coupled to the
# actual GPU driver stack of whichever machine runs the binary (Mesa/AMD,
# Mesa/Intel, proprietary NVIDIA, ...), never something safe to freeze at
# build time. Confirmed via a real crash: NVIDIA's own EGL/Wayland
# integration on a real machine called into this bundled, mismatched copy
# and segfaulted inside it (SIGSEGV in libgbm.so.1's gbm_create_device).
# Excluding it here means the dynamic linker falls through to the running
# machine's own /usr/lib/libgbm.so.1 at runtime instead - every other
# GL/EGL/DRM/Wayland library already resolves from the system this same way
# and was never bundled in the first place.
a.binaries = [b for b in a.binaries if not b[0].startswith("libgbm.so")]

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
    icon=str(_icon_path) if _icon_is_valid_ico else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Pochtalion",
)
