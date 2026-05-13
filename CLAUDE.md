# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the application
python main.py

# Install dependencies
pip install -r requirements.txt

# Build standalone executable (Windows target)
python -m PyInstaller --onefile --noconsole --icon=icon.ico \
  --hidden-import=aiosqlite --hidden-import=core.paths --hidden-import=core.logger \
  --hidden-import=core.database --hidden-import=appdirs --hidden-import=PyQt6 \
  --hidden-import=PyQt6.QtWebEngineWidgets --hidden-import=PyQt6.QtWebChannel \
  --hidden-import=qasync --hidden-import=bridges.chat_bridge \
  --hidden-import=bridges.settings_bridge --hidden-import=bridges.sidebar_bridge \
  --hidden-import=modules.sessions_manager --hidden-import=modules.parser \
  --hidden-import=modules.mailer --hidden-import=core.settings_manager \
  --hidden-import=core.notification_manager --hidden-import=requests \
  --hidden-import=cachetools \
  --add-data "settings/*;settings/" --add-data "database/database.db;database/" \
  --add-data "web/*;web/" --add-data "assets/*;assets" \
  --add-data "logs;logs/" --add-data "tmp;tmp/" --add-data "icon.ico;." \
  main.py
```

There is no test suite and no linter configured.

## Architecture

Pochtalion is a Telegram mass-mailing/parsing desktop application. It has a **PyQt6 backend** and a **Qt WebEngine frontend** — three HTML/CSS/JS pages rendered inside `QWebEngineView` widgets and communicating with Python over `QWebChannel`.

### Event loop

`main.py` runs a single `qasync` event loop that drives both Qt's event system and Python `asyncio`. All async work (Telegram API calls, DB queries) runs cooperatively on this loop. Never use `asyncio.run()` or create a separate thread — everything is one loop.

### Python ↔ JavaScript bridge pattern

Each UI panel has a bridge class inheriting `BaseBridge(QObject)`. Bridges are registered with `QWebChannel` and exposed to JS as `channel.objects.<name>`. 

- **Python → JS**: `pyqtSignal` fields on the bridge class. JS calls `bridge.signalName.connect(jsCallback)`.
- **JS → Python**: methods decorated with `@asyncSlot(...)` or `@pyqtSlot(...)`. JS calls `await bridge.methodName(args)`.

The three bridges:
| Bridge | JS page | Purpose |
|--------|---------|---------|
| `SidebarBridge` | `sidebar.html` | Dialog list, session selector, notifications |
| `ChatBridge` | `chat.html` | Message display and sending |
| `SettingsBridge` | `settings.html` | Sessions, parsing, mailing, SMM content |

### Session management

`SessionsManager` holds a `dict[session_file → ClientWrapper]`. Each `ClientWrapper` wraps a Telethon `TelegramClient` and owns event handlers for incoming messages. Sessions are identified by both `session_file` (string, used as dict key) and `session_id` (integer, DB primary key).

`get_or_start_session(id, file)` is the safe entry point — it starts the session if not already running and returns the wrapper.

### Mailing and parsing lifecycle

`Mailer` and `Parser` are long-running modules attached to `main_window`. They each:
1. Start their own `asyncio.Task` via `asyncio.create_task()` from the bridge slot
2. Spin up temporary `ClientWrapper` sessions via `start_sessions()` (using `is_module=True` to skip old-dialog fetch)
3. Report progress by emitting bridge signals from an inner `sendUpdate()` task
4. Clean up in `stop()`, which is called both externally (user clicks stop) and internally (loop exhausted)

`GroupMailer` follows the same pattern but manages one `asyncio.Task` per session (stored in `GroupMail` model objects in `work_sessions: dict[str, GroupMail]`). It is initialized at app startup with one `GroupMail` per DB session.

### Database

Single SQLite file at `database/database.db`, accessed through `core/database.py` via `aiosqlite` with a single `asyncio.Lock` serialising all writes. On `.exe` builds, the DB is copied to `appdirs.user_data_dir("Pochtalion")`. The schema has: `sessions`, `users`, `user_sessions`, `messages`, `smm_messages`, `smm_voices`, `parse_source`.

### User status bitmask (`config.py`)

User statuses are 3-bit flags stored in the `user_status` column:
```
bit 2 (4): we added the user (1) vs user wrote himself (0)
bit 1 (2): working with existing dialog (1) vs event adding (0)
bit 0 (1): we replied/sent (1) vs waiting (0)
```
Status 4 = user from parsing. Status 6 = added from search.

### File storage layout (`core/paths.py`)

```
assets/
  sessions/        *.session files (Telethon)
  profile_photos/  <session_file>/<user_id>.jpg
  users_data/      <user_id>_<session_file>/  (message attachments)
  smm/
    smm_images/    images attached to SMM messages
    smm_voices/    voice files for voice mailing
database/database.db
settings/defaults.json   (shipped)
settings/settings.json   (user, gitignored in production)
tmp/                     temporary voice files for the SMM picker
logs/                    one .log per module
```

### Settings

`SettingsManager` loads `settings/settings.json` (copied from `defaults.json` on first run). Access via `main_window.settings_manager.get_setting(key)`. Changing `api_keys` automatically re-initialises `SessionsManager`.

### Key implementation details

- `sendGroupMessage` in `ClientWrapper` auto-joins a channel via `JoinChannelRequest` if the session is not a participant before sending.
- `NotificationManager` tracks unread dialogs in memory and persists them to the `user_sessions.is_read` column on shutdown.
- The `parsing_task` and `mailing_task` on `SettingsBridge` can be `None` before first use — always check before cancelling.
- When adding a new bridge signal that Python must emit from a background module (e.g., `GroupMailer`), access it as `self.main_window.settings_bridge.<signal>.emit(...)` — the bridge is available after `init_async()` completes.
