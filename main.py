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


if __name__ == "__main__":
    asyncio.run(main())
