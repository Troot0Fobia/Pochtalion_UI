"""One-off maintenance script: re-resolves every `parse_source` row and
repairs a stale/missing `chat_username` (and `chat_type`) without a full
re-parse of the group's members.

Why it exists
-------------
Telegram lets a chat carry several usernames at once - a base handle plus
purchased "collectible"/Fragment ones, all pointing at the same peer. The
moment a chat has more than one, the scalar `username` field in the API
response comes back empty and every handle lands in the `usernames` list
instead. The parser used to read only `.username`, so such a chat was
saved with `chat_username = NULL` and the mailer then treated a fully
public group as private: it can only be reached through the
membership-gated `-100{id}` path, one `get_entity` failure permanently
benches a session for that chat (`chat_access.has_access = 0`), and a run
whose selected session is benched skips every user from that group.

What it does
------------
For each `parse_source` row:
  * resolves the chat through each connected session (tries the
    `-100{id}` channel id, then the `-{id}` basic-group id);
  * recomputes the username with `parser.entity_username` (which reads the
    `usernames` list) and the type with `parser.classify_chat_entity`;
  * refreshes `chat_access` (true/false) for every session it probed;
  * if the username or type actually changed, updates `parse_source`;
  * if the row ends up with a public username, drops the stale
    `has_access = 0` rows for that chat - with a public handle every
    session can reach it regardless of membership.

Pass --dry-run to see the diff without touching the database.

IMPORTANT: run this with the main app closed. It connects directly to the
same .session files the app uses, and Telethon's sqlite-backed session
storage does not tolerate two processes touching the same file at once.

Usage:
    python scripts/maintenance/repair_chat_usernames.py [--db PATH] [--dry-run]
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from telethon import TelegramClient

from core.database import Database
from core.paths import SESSIONS, SETTINGS
from modules.parser import classify_chat_entity, entity_username

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


async def _resolve_everywhere(chat_id: int, sessions: list):
    """Probe every session for this chat. Returns
    (entity_or_None, {session_id: has_access})."""
    candidates = (int(f"-100{chat_id}"), -chat_id)
    access: dict[int, bool] = {}
    best_entity = None

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
            access[session_id] = False
            continue

        chat_type, has_access = classify_chat_entity(entity)
        access[session_id] = has_access
        # Prefer an entity we actually have access to (a ChannelForbidden
        # stub carries the type but never a username); among those, prefer
        # one that yields a username.
        if best_entity is None:
            best_entity = entity
        else:
            best_has = classify_chat_entity(best_entity)[1]
            if (has_access and not best_has) or (
                has_access == best_has
                and entity_username(entity)
                and not entity_username(best_entity)
            ):
                best_entity = entity
        await asyncio.sleep(CANDIDATE_DELAY)

    return best_entity, access


async def _repair_row(
    database: Database, row: dict, sessions: list, dry_run: bool
) -> None:
    chat_id = row["chat_id"]
    title = row["chat_title"]
    old_username = row["chat_username"] or None
    old_type = row["chat_type"]

    entity, access = await _resolve_everywhere(chat_id, sessions)

    if not dry_run:
        for session_id, has_access in access.items():
            await database.set_chat_access(chat_id, session_id, has_access)

    if entity is None:
        print(
            f"  [{chat_id}] '{title}': ни одна сессия не смогла зарезолвить чат "
            f"— пропуск"
        )
        return

    new_type = classify_chat_entity(entity)[0] or old_type
    resolved_username = entity_username(entity)
    # never downgrade a known handle to NULL on a pass that only saw a
    # Forbidden stub
    new_username = resolved_username or old_username
    new_title = getattr(entity, "title", None) or title

    changes = []
    if new_username != old_username:
        changes.append(f"username: {old_username!r} -> {new_username!r}")
    if new_type != old_type:
        changes.append(f"type: {old_type!r} -> {new_type!r}")
    if new_title != title:
        changes.append(f"title: {title!r} -> {new_title!r}")

    if changes:
        print(f"  [{chat_id}] '{title}': " + "; ".join(changes))
        if not dry_run:
            await database.update_parse_source_meta(
                chat_id, new_title, new_username, new_type
            )
    else:
        print(f"  [{chat_id}] '{title}': без изменений")

    if new_username:
        denials = [sid for sid, ok in access.items() if not ok]
        if dry_run:
            # can't know the persisted count without writing; show probe view
            if denials:
                print(
                    f"      публичный @{new_username} — при реальном запуске будут "
                    f"сняты негативные метки доступа ({len(denials)} сессий в пробе)"
                )
        else:
            removed = await database.clear_chat_access_denials(chat_id)
            if removed:
                print(
                    f"      публичный @{new_username} — снято {removed} негативных "
                    f"меток доступа (chat_access)"
                )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        help="путь к database.db (по умолчанию — база приложения)",
        default=None,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать, что изменится, ничего не записывая",
    )
    args = parser.parse_args()

    api_keys = _load_api_keys()
    if not api_keys:
        print("Не найден валидный api_id:api_hash в settings.json, выход.")
        return
    api_id, api_hash = api_keys

    database = await Database.create(args.db)
    sessions = []
    try:
        rows = await database.get_all_parse_sources()
        if not rows:
            print("Таблица parse_source пуста.")
            return
        print(
            f"parse_source: {len(rows)} записей "
            f"({sum(1 for r in rows if not r['chat_username'])} без username)."
        )
        if args.dry_run:
            print("--- DRY RUN: изменения не записываются ---")

        sessions = await _connect_sessions(database, api_id, api_hash)
        if not sessions:
            print("Ни одна сессия не подключилась, выход.")
            return
        print(f"Подключено сессий: {len(sessions)}\n")

        for row in rows:
            await _repair_row(database, row, sessions, args.dry_run)
    finally:
        for _, _, client in sessions:
            await client.disconnect()
        await database.closeConnection()


if __name__ == "__main__":
    asyncio.run(main())
