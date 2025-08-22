## Install requirements

`pip install -r requirements.txt`

## Creating exe

 `python -m PyInstaller --onefile --noconsole --icon=icon.ico --hidden-import=aiosqlite --hidden-import=core.paths --hidden-import=core.logger --hidden-import=core.database --hidden-import=appdirs --hidden-import=PyQt6 --hidden-import=PyQt6.QtWebEngineWidgets --hidden-import=PyQt6.QtWebChannel --hidden-import=qasync --hidden-import=bridges.chat_bridge --hidden-import=bridges.settings_bridge --hidden-import=bridges.sidebar_bridge --hidden-import=modules.sessions_manager --hidden-import=modules.parser --hidden-import=modules.mailer --hidden-import=core.settings_manager --hidden-import=core.notification_manager --hidden-import=requests --hidden-import=cachetools --add-data "settings/*;settings/" --add-data "database/database.db;database/" --add-data "web/*;web/" --add-data "assets/*;assets" --add-data "logs;logs/" --add-data "tmp;tmp/" --add-data "icon.ico;." main.py`
