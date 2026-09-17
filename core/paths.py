"""Filesystem layout for Pochtalion.

There are two kinds of paths:

* **Resources** — read-only files shipped with the app (``web/``, ``settings/defaults.json``,
  ``pochtalion.ico``). They live next to the source tree in development and inside the
  PyInstaller bundle (``sys._MEIPASS``) when frozen.
* **User data** — everything the app writes at runtime (database, settings, Telethon
  sessions, downloaded photos, SMM media, logs, temp files). The location is decided once,
  at import time, by :func:`_resolve_mode`:

  ``env``
      ``POCHTALION_DATA_DIR`` is set — every category becomes a sub-directory of it.
      Wins regardless of install form.
  ``portable``
      Frozen, no env override, and :func:`_detect_install_form` says
      ``INSTALL_FORM`` is ``directory`` or ``appimage`` — i.e. the user just extracted
      an archive or placed an AppImage somewhere themselves, with no real installer
      involved. Data goes in ``<exe_dir>/data/``, right next to the executable, no
      marker file needed - this used to require a ``portable.txt`` file, which was easy
      to forget and, when forgotten, meant two unrelated copies of the app could end up
      silently sharing (and corrupting) the same OS-standard data directory instead.
  ``standalone``
      Frozen, no env override, and ``INSTALL_FORM`` is ``windows-installer`` - a real
      Inno Setup install. Data goes in the OS-standard per-user location (via
      ``platformdirs``), separate from the install directory, matching normal Windows
      app conventions for something that has a proper installer/uninstaller.
  ``dev``
      Running from source — the legacy in-repo layout (``database/``, ``assets/``,
      ``logs/``, ``tmp/``, ``settings/``) so a developer's working data stays put.

In ``env`` and ``portable`` mode the XDG split does not apply: config / data / logs / cache
are just sub-directories of one root.

MODE is derived from :func:`_detect_install_form` / ``INSTALL_FORM`` (computed first, see
below) rather than being independent of it - which install form is the right signal for
where data should live too, since only ``windows-installer`` implies a "real",
OS-registered install with its own uninstaller.
"""

import os
import sys
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "Pochtalion"
ENV_DATA_DIR = "POCHTALION_DATA_DIR"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _real_exe_path() -> Path | None:
    """The actual, on-disk file this install *is* - what a self-update apply
    step swaps/relaunches, and what portable data should sit next to. None
    outside a frozen build.

    Deliberately not just sys.executable: inside a running AppImage, that
    points at the ephemeral FUSE mountpoint the AppImage runtime extracts
    itself to (/tmp/.mount_XXXXXX/usr/bin/Pochtalion) - read-only, and a
    different random path every single launch. $APPIMAGE is the AppImage
    runtime's own pointer to the real .AppImage file the user actually has
    on disk, and is what must be used instead for both of those purposes.
    """
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return Path(appimage).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def _exe_dir() -> Path:
    """Directory that holds the running executable (frozen) or the repo root (source)."""
    real = _real_exe_path()
    return real.parent if real is not None else _repo_root()


# --- resources (read-only, shipped with the app) --------------------------------

def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller onefile -> temp extraction dir; onedir -> _internal
        return Path(getattr(sys, "_MEIPASS", _exe_dir()))
    return _repo_root()


RESOURCE_ROOT = _resource_root()
WEB = RESOURCE_ROOT / "web"
DEFAULTS = RESOURCE_ROOT / "settings" / "defaults.json"
ICON = RESOURCE_ROOT / "pochtalion.ico"
# Plain-text VERSION file, not a Python module, so build tooling can read it
# with a one-line `cat`/`Get-Content` regardless of how the rest of the
# source tree is organized.
VERSION = (RESOURCE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
# "owner/repo" the self-updater checks GitHub releases against - baked in at
# build time from the POCHTALION_UPDATE_REPO env var (see build/pochtalion.spec
# and build/README.md), never hardcoded in source. This file is gitignored and
# not part of the dev-mode source tree, so REPO is empty unless a real build
# generated it - modules.updater treats that as "update checking disabled",
# which is the correct default for a dev run.
_repo_file = RESOURCE_ROOT / "REPO"
REPO = _repo_file.read_text(encoding="utf-8").strip() if _repo_file.exists() else ""
# The detached self-update helper script for this platform - a real,
# reviewable file bundled via pochtalion.spec (build/scripts/), not a string
# generated at update time. None in dev mode (nothing bundles it there, and
# apply never runs in dev mode anyway).
UPDATE_HELPER = (
    RESOURCE_ROOT / "scripts" / ("apply_update.ps1" if sys.platform.startswith("win") else "apply_update.sh")
    if getattr(sys, "frozen", False)
    else None
)


def resource_path(relative_path) -> str:
    """Absolute path to a bundled resource. Absolute inputs are returned unchanged."""
    p = Path(relative_path)
    return str(p if p.is_absolute() else RESOURCE_ROOT / p)


# --- install form (computed first: MODE below depends on it) -----------------

def _detect_install_form() -> str:
    """How the running app's own files are physically distributed.

    ``dev``
        Running from source - never applicable to a self-update.
    ``appimage``
        A single AppImage file (Linux) - apply replaces just that one file.
    ``windows-installer``
        Installed via build/installer.iss (Inno Setup), which always drops an
        ``unins*.exe`` next to the executable - apply re-runs the downloaded
        installer silently over the same directory.
    ``directory``
        Anything else frozen: a raw tar.gz/zip extraction on Linux or Windows
        with no uninstaller present - apply needs a full directory-swap.
    """
    if not getattr(sys, "frozen", False):
        return "dev"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if sys.platform.startswith("win") and any(_exe_dir().glob("unins*.exe")):
        return "windows-installer"
    return "directory"


INSTALL_FORM = _detect_install_form()
# Where the running executable actually lives - what a self-update apply step
# replaces/swaps and what it relaunches. None in dev mode: sys.executable is
# the Python interpreter there, not a Pochtalion binary, and apply never runs
# in dev mode anyway (REPO is always empty -> update checking is disabled).
# See _real_exe_path() for why this isn't just sys.executable for AppImage.
EXE_DIR = _exe_dir()
EXE_PATH = _real_exe_path()


# --- user data location --------------------------------------------------------

def _resolve_mode() -> str:
    if os.environ.get(ENV_DATA_DIR):
        return "env"
    if INSTALL_FORM == "dev":
        return "dev"
    if INSTALL_FORM == "windows-installer":
        return "standalone"
    # appimage / directory: the user placed this themselves, no real installer
    return "portable"


MODE = _resolve_mode()
IS_PORTABLE = MODE in ("env", "portable")


def _category_roots() -> tuple[Path, Path, Path, Path]:
    """Return (config, data, logs, cache) roots for the current mode.

    For ``env`` / ``portable`` the "data" category is the root itself (so the folder
    reads as ``<root>/database.db``, ``<root>/sessions/`` …) and only config / logs /
    cache get their own sub-directory.
    """
    if MODE == "env":
        root = Path(os.environ[ENV_DATA_DIR]).expanduser()
        return root / "config", root, root / "logs", root / "cache"
    if MODE == "portable":
        root = _exe_dir() / "data"
        return root / "config", root, root / "logs", root / "cache"
    if MODE == "standalone":
        d = PlatformDirs(APP_NAME, appauthor=False)
        return d.user_config_path, d.user_data_path, d.user_log_path, d.user_cache_path
    # dev: legacy in-repo layout
    root = _repo_root()
    return root / "settings", root / "assets", root / "logs", root / "tmp"


CONFIG_DIR, DATA_DIR, LOGS, _CACHE_DIR = _category_roots()

# --- config ---
SETTINGS = CONFIG_DIR

# --- data ---
# In dev the database keeps its historical home (repo/database/); elsewhere it sits
# in the data directory next to the sessions.
DB_PATH = (_repo_root() / "database" / "database.db") if MODE == "dev" else DATA_DIR / "database.db"
DATABASE = DB_PATH.parent
SESSIONS = DATA_DIR / "sessions"
USERS_DATA = DATA_DIR / "users_data"
SMM = DATA_DIR / "smm"
SMM_IMAGES = SMM / "smm_images"
SMM_VOICES = SMM / "smm_voices"
PROFILE_PHOTOS = DATA_DIR / "profile_photos"
GROUP_PHOTOS = DATA_DIR / "group_photos"
SESSION_PHOTOS = DATA_DIR / "session_photos"
# Downloaded-but-not-yet-applied self-update files. Deliberately under DATA_DIR,
# not TMP: TMP is wiped on every close (see Pochtalion_UI.closeEvent), but an
# update must survive the very close/relaunch cycle that applies it.
UPDATES = DATA_DIR / "updates"

# --- cache ---
# In dev mode _CACHE_DIR already *is* the tmp directory (repo/tmp).
TMP = _CACHE_DIR if MODE == "dev" else _CACHE_DIR / "tmp"

# Directories the app must be able to write to on startup.
RUNTIME_DIRS = (
    CONFIG_DIR,
    DATA_DIR,
    DATABASE,
    SESSIONS,
    USERS_DATA,
    SMM_IMAGES,
    SMM_VOICES,
    PROFILE_PHOTOS,
    GROUP_PHOTOS,
    SESSION_PHOTOS,
    UPDATES,
    LOGS,
    TMP,
)


def init_dirs() -> None:
    for path in RUNTIME_DIRS:
        path.mkdir(parents=True, exist_ok=True)


# Create the writable layout as soon as anything imports this module, so loggers
# and the database can open files without worrying about import order.
init_dirs()
