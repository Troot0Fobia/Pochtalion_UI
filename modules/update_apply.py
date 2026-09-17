import asyncio
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

from core.logger import setup_logger
from core.paths import EXE_DIR, EXE_PATH, INSTALL_FORM, UPDATE_HELPER, UPDATES

logger = setup_logger("Pochtalion.UpdateApply", "update_apply.log")

# Must match the allowlist hardcoded in build/scripts/apply_update.{sh,ps1} -
# the exact, fixed set of top-level entries PyInstaller's onedir output ever
# produces (build/pochtalion.spec: COLLECT(..., name="Pochtalion")). apply
# only ever touches these, inside the install dir, never the whole directory
# - so a portable data/ folder, or a POCHTALION_DATA_DIR that happens to live
# inside or alongside the install dir, is guaranteed to survive untouched.
APP_OWNED_NAMES = frozenset({"Pochtalion", "Pochtalion.exe", "_internal"})


def check_swap_is_safe(install_dir: Path, data_dir: Path) -> None:
    """Raise if data_dir could plausibly be deleted by a directory-form apply.

    Cheap, deliberate guard against POCHTALION_DATA_DIR (or a portable
    install's data/ folder) being pointed at a path that collides with one of
    the names apply is about to delete and replace.
    """
    install_dir = install_dir.resolve()
    data_dir = data_dir.resolve()
    if data_dir == install_dir:
        # Data lives directly in the install root, alongside the app's own
        # files (e.g. POCHTALION_DATA_DIR pointed at the exe's own
        # directory) - apply still only ever touches APP_OWNED_NAMES inside
        # it, so this is fine.
        return
    try:
        relative = data_dir.relative_to(install_dir)
    except ValueError:
        return  # data lives entirely outside the install dir
    if relative.parts and relative.parts[0] in APP_OWNED_NAMES:
        raise RuntimeError(
            f"data directory {data_dir} is inside {relative.parts[0]!r}, which "
            "a directory-swap update would delete - refusing to apply"
        )


async def extract_archive(archive_path: Path, dest_dir: Path) -> Path:
    """Extract a downloaded tar.gz/zip release asset; return the Pochtalion/
    onedir folder inside it.

    Extracts one member at a time with a yield in between, rather than a
    single extractall() call - _internal/ has thousands of entries (the full
    Qt/WebEngine bundle), and extractall() run synchronously froze the whole
    Qt/asyncio event loop (no repaints, no clicks) for the several seconds it
    took, right as prepare() ran on an already-cached update at startup.
    """
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            for member in zf.namelist():
                zf.extract(member, dest_dir)
                await asyncio.sleep(0)
    else:
        with tarfile.open(archive_path) as tf:
            for member in tf.getmembers():
                tf.extract(member, dest_dir, filter="data")
                await asyncio.sleep(0)

    extracted = dest_dir / "Pochtalion"
    if not extracted.is_dir():
        raise RuntimeError(f"{archive_path} has no top-level Pochtalion/ folder")

    unexpected = {p.name for p in extracted.iterdir()} - APP_OWNED_NAMES
    if unexpected:
        raise RuntimeError(f"downloaded build has unexpected top-level entries: {unexpected}")

    return extracted


async def prepare(downloaded_path: Path, data_dir: Path) -> dict:
    """Validate everything apply will need, while the app is still fully
    running - so a problem here surfaces as an error message instead of a
    half-applied update. Returns plain data for launch_and_exit(); nothing
    here needs to run again after this point."""
    if UPDATE_HELPER is None or EXE_PATH is None:
        raise RuntimeError("update apply is not available outside a real build")

    if INSTALL_FORM == "directory":
        check_swap_is_safe(EXE_DIR, data_dir)
        new_build_dir = await extract_archive(downloaded_path, UPDATES / "staging")
        return {"form": "directory", "install_dir": str(EXE_DIR), "new_build_dir": str(new_build_dir)}

    if INSTALL_FORM == "appimage":
        return {"form": "appimage", "current": str(EXE_PATH), "new": str(downloaded_path)}

    if INSTALL_FORM == "windows-installer":
        return {"form": "windows-installer", "installer_path": str(downloaded_path)}

    raise RuntimeError(f"no apply strategy for install form {INSTALL_FORM!r}")


def launch_and_exit(args: dict) -> None:
    """Copy the bundled helper script out to a scratch location - independent
    of the install dir it may be about to swap, so it can't delete itself
    mid-run - then launch it fully detached (it outlives this process) and
    return. The caller is expected to close the app immediately after this.

    Deliberately under UPDATES, not TMP: Pochtalion_UI.closeEvent wipes TMP
    on every close, and that close is about to happen right after this
    returns - a helper script (or, for the directory form, the staged new
    build from prepare()) placed under TMP could be deleted out from under
    the detached process before it even gets to run.
    """
    assert UPDATE_HELPER is not None, "launch_and_exit() called outside a real build"
    helper = UPDATES / UPDATE_HELPER.name
    shutil.copy2(UPDATE_HELPER, helper)
    helper.chmod(0o755)

    pid = os.getpid()
    form = args["form"]

    # Pochtalion.exe is a windowed (console=False) build, so it has no real
    # console/stdio handles to inherit. Leaving stdin/stdout/stderr as the
    # subprocess.Popen default (None -> "inherit") makes Windows try to
    # duplicate handles that don't exist, which raises
    # `OSError: [WinError 6] The handle is invalid` from inside Popen() itself
    # - before the helper ever launches. DEVNULL would dodge that too, but it
    # also throws away the only chance to ever see why the helper failed once
    # the app that spawned it is gone - route stdout/stderr to a log file
    # under UPDATES (survives the close, unlike TMP) instead. stdin still
    # has nothing useful to read from, so that one stays DEVNULL.
    helper_log = (UPDATES / "helper_output.log").open("wb")

    if sys.platform.startswith("win"):
        # Bare "powershell" is resolved via PATH search at CreateProcess time -
        # with a DETACHED_PROCESS + CREATE_BREAKAWAY_FROM_JOB child spawned
        # from a windowed app, that resolution has been unreliable in practice
        # (the process object comes back fine, but nothing the script does
        # ever happens - not even its own Start-Transcript line at the very
        # top). The full path removes that ambiguity entirely.
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        cmd = [
            str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper),
            "-Form", form, "-TargetPid", str(pid), "-ExePath", str(EXE_PATH),
        ]
        if form == "directory":
            cmd += ["-InstallDir", args["install_dir"], "-NewBuildDir", args["new_build_dir"]]
        elif form == "windows-installer":
            cmd += ["-InstallerPath", args["installer_path"]]
        proc = subprocess.Popen(
            cmd,
            # powershell.exe is a CONSOLE-subsystem app (unlike Pochtalion.exe
            # itself, which has none at all) - confirmed by testing that the
            # exact same command line runs perfectly from a normal cmd/PowerShell
            # window, but silently no-ops (exits 0 in well under a second,
            # nothing written anywhere, not even its own Start-Transcript line)
            # when Python spawns it with DETACHED_PROCESS. CREATE_NO_WINDOW
            # gives it a real (just hidden) console instead of none at all,
            # which is the documented/standard flag for this exact scenario -
            # a hidden console app launched from a windowed one.
            # CREATE_BREAKAWAY_FROM_JOB still guards against being killed
            # alongside Pochtalion.exe if it's in a Job Object with kill-on-close.
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_BREAKAWAY_FROM_JOB
            ),
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=helper_log,
            stderr=subprocess.STDOUT,
        )
    else:
        if form == "directory":
            cmd = [str(helper), "directory", str(pid), args["install_dir"], args["new_build_dir"]]
        else:  # appimage
            cmd = [str(helper), "appimage", str(pid), args["current"], args["new"]]
        proc = subprocess.Popen(
            cmd,
            start_new_session=True,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=helper_log,
            stderr=subprocess.STDOUT,
        )
    helper_log.close()

    logger.info("Update apply helper launched (form=%s, target_pid=%s, helper_pid=%s)", form, pid, proc.pid)
