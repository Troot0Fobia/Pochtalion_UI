"""One-off maintenance script: reclassifies parse_source rows whose
chat_type predates access-aware classification - legacy "unknown" (or
other garbage) values written before the parser.py/mailer.py rework that
stopped ever writing chat_type="unknown" and started recording, per
session, whether it has access to a given chat (chat_access table - both
outcomes are kept, keyed by (chat_id, session_id); rows only accumulate
for genuinely restricted chats, bounded by the number of Telegram
accounts the app manages, not by user/message count).

For every affected chat_id, tries each saved session against the
-100{id} (channel) and -{id} (basic chat) identifiers until one succeeds,
classifies the result with modules.parser.classify_chat_entity, updates
parse_source.chat_type with whatever type could be determined (even from a
Forbidden object - the type is usually still derivable without access),
and records a chat_access row (true or false) for every session tried.
Unlike the normal parsing/mailing flow, this script deliberately probes
every saved session for every broken row - that's fine here since it's a
one-time, manually triggered maintenance pass, not a cost paid on every
mailing run.

IMPORTANT: run this with the main app closed. It connects directly to the
same .session files the app uses, and Telethon's sqlite-backed session
storage does not tolerate two processes touching the same file at once.

Usage:
    python scripts/repair_parse_source.py
"""

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient

from core.database import Database
from core.paths import SESSIONS, SETTINGS
from modules.parser import classify_chat_entity

CANDIDATE_DELAY = 0.5


def _load_api_keys() -> tuple[int, str] | None:
    candidates = [
        SETTINGS / "settings.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        api_keys = (data.get("api_keys") or "").strip()
        if not api_keys or ":" not in api_keys:
            continue
        api_id, _, api_hash = api_keys.partition(":")
        if re.fullmatch(r"\d{5,8}", api_id) and re.fullmatch(r"[a-fA-F0-9]{32}", api_hash):
            return int(api_id), api_hash
    return None


async def _connect_sessions(database: Database, api_id: int, api_hash: str):
    connected = []
    for session in await database.get_sessions():
        session_file = session["session_file"]
        client = TelegramClient(str(SESSIONS / session_file), api_id, api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            print(f"  сессия {session_file} не авторизована, пропуск")
            await client.disconnect()
            continue
        connected.append((session["session_id"], session_file, client))
    return connected


async def _repair_row(database: Database, row: dict, sessions: list) -> None:
    chat_id = row["chat_id"]
    candidates = (int(f"-100{chat_id}"), -chat_id)
    resolved_type = None

    for session_id, session_file, client in sessions:
        entity = None
        for candidate in candidates:
            try:
                entity = await client.get_entity(candidate)
                break
            except Exception:
                await asyncio.sleep(CANDIDATE_DELAY)
                continue
        if entity is None:
            continue

        chat_type, has_access = classify_chat_entity(entity)
        if chat_type is None:
            continue

        await database.set_chat_access(chat_id, session_id, has_access)
        if resolved_type is None:
            resolved_type = chat_type
        print(
            f"  chat_id={chat_id} '{row['chat_title']}': сессия {session_file} -> "
            f"type={chat_type}, access={has_access}"
        )
        await asyncio.sleep(CANDIDATE_DELAY)

    if resolved_type is not None:
        await database.update_parse_source_type(chat_id, resolved_type)
    else:
        print(
            f"  chat_id={chat_id} '{row['chat_title']}': не удалось "
            f"классифицировать ни одной сессией (chat_type оставлен без изменений)"
        )


async def main() -> None:
    api_keys = _load_api_keys()
    if not api_keys:
        print("Не найден валидный api_id:api_hash в settings.json, выход.")
        return
    api_id, api_hash = api_keys

    database = await Database.create()
    sessions = []
    try:
        rows = await database.get_unclassified_parse_sources()
        if not rows:
            print("Записей parse_source с нераспознанным chat_type не найдено.")
            return
        print(f"Найдено {len(rows)} записей для починки.")

        sessions = await _connect_sessions(database, api_id, api_hash)
        if not sessions:
            print("Ни одна сессия не смогла подключиться, выход.")
            return
        print(f"Подключено сессий: {len(sessions)}")

        for row in rows:
            await _repair_row(database, row, sessions)
    finally:
        for _, _, client in sessions:
            await client.disconnect()
        await database.closeConnection()


if __name__ == "__main__":
    asyncio.run(main())
