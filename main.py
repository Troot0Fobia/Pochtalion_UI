import sys
import asyncio
from pathlib import Path
from qasync import QEventLoop, QApplication
from ui.pochtalion_ui import Pochtalion_UI
from core.paths import (
    ASSETS, USERS_DATA, PROFILE_PHOTOS, LOGS, TMP, DATABASE, SMM_IMAGES, SESSIONS
)

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


def init_folders():
    ASSETS.mkdir(parents=True, exist_ok=True)
    USERS_DATA.mkdir(parents=True, exist_ok=True)
    PROFILE_PHOTOS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    DATABASE.mkdir(parents=True, exist_ok=True)
    SMM_IMAGES.mkdir(parents=True, exist_ok=True)
    SESSIONS.mkdir(parents=True, exist_ok=True)

if __name__ == "__main__":
    init_folders()
    asyncio.run(main())