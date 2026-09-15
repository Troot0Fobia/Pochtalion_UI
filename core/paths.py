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
  ``portable``
      A ``portable.txt`` file sits next to the executable — data goes in ``<exe_dir>/data/``.
  ``standalone``
      Frozen build without a marker — the OS-standard per-user locations (XDG on Linux)
      resolved through ``platformdirs``.
  ``dev``
      Running from source — the legacy in-repo layout (``database/``, ``assets/``,
      ``logs/``, ``tmp/``, ``settings/``) so a developer's working data stays put.

In ``env`` and ``portable`` mode the XDG split does not apply: config / data / logs / cache
are just sub-directories of one root.
"""

import os
import sys
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "Pochtalion"
ENV_DATA_DIR = "POCHTALION_DATA_DIR"
PORTABLE_MARKER = "portable.txt"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _exe_dir() -> Path:
    """Directory that holds the running executable (frozen) or the repo root (source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _repo_root()


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


def resource_path(relative_path) -> str:
    """Absolute path to a bundled resource. Absolute inputs are returned unchanged."""
    p = Path(relative_path)
    return str(p if p.is_absolute() else RESOURCE_ROOT / p)


# --- user data location --------------------------------------------------------

def _resolve_mode() -> str:
    if os.environ.get(ENV_DATA_DIR):
        return "env"
    if (_exe_dir() / PORTABLE_MARKER).exists():
        return "portable"
    if getattr(sys, "frozen", False):
        return "standalone"
    return "dev"


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
    LOGS,
    TMP,
)


def init_dirs() -> None:
    for path in RUNTIME_DIRS:
        path.mkdir(parents=True, exist_ok=True)


# Create the writable layout as soon as anything imports this module, so loggers
# and the database can open files without worrying about import order.
init_dirs()
