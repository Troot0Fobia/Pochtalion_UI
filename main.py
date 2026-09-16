import asyncio
import sys

from qasync import QApplication, QEventLoop

# Importing core.paths creates the writable directory layout for the current mode
# (dev / portable / standalone). Keep this before other project imports.
import core.paths  # noqa: F401
from ui.pochtalion_ui import Pochtalion_UI


async def main():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    window = Pochtalion_UI()
    await window.init_async()
    window.show()

    with loop:
        loop.run_until_complete(app_close_event.wait())

    window.close()
    app.quit()
    sys.exit(0)


def _selfcheck() -> int:
    """Display-free smoke test used by the build pipeline.

    Imports every module that must be present in a frozen bundle, loads the
    offscreen Qt platform plugin, resolves the runtime paths, and prints the
    version. It does NOT start the event loop or touch QtWebEngine. Exit 0 means
    the bundle is structurally sound.
    """
    import importlib

    for mod in (
        "PyQt6.QtWidgets",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebChannel",
        "qasync",
        "telethon",
        "aiosqlite",
        "qrcode",
        "PIL",
        "tzlocal",
        "puremagic",
    ):
        importlib.import_module(mod)

    from PyQt6.QtWidgets import QApplication as _QApp

    _QApp(["pochtalion", "-platform", "offscreen"])

    print(f"Pochtalion {core.paths.VERSION}")
    print(f"mode={core.paths.MODE} resources={core.paths.RESOURCE_ROOT} data={core.paths.DATA_DIR}")
    print(f"install_form={core.paths.INSTALL_FORM} exe_dir={core.paths.EXE_DIR}")
    return 0


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        sys.exit(_selfcheck())
    asyncio.run(main())
