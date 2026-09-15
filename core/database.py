import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path

import aiosqlite
import tzlocal
from pytz import timezone

from core.paths import DB_PATH, SMM_VOICES

KNOWN_CHAT_TYPES = frozenset({"broadcast", "megagroup", "gigagroup", "chat"})


class Database:

    def __init__(self, db):
        self._db = db
        self._lock = asyncio.Lock()

    @classmethod
    async def create(cls, db_path: str | Path | None = None):
        # db_path is an explicit override used by one-off maintenance
        # scripts that need to open an arbitrary database file; the app
        # itself always calls create() with no argument.
        if db_path is not None:
            target = Path(db_path)
            if not target.exists():
                open(target, "a").close()
            db = await aiosqlite.connect(target)
            db.row_factory = sqlite3.Row
            await db.execute("PRAGMA foreign_keys = ON")
            return cls(db)

        # The schema is fully created below via "CREATE TABLE IF NOT EXISTS", so an
        # empty file is enough for a fresh install. DB_PATH is resolved by core.paths
        # (in-repo in dev, per-user data dir when installed, <exe>/data when portable).
        if not DB_PATH.exists():
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            open(DB_PATH, "a").close()

        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = sqlite3.Row  # For mapping rows

        await db.execute("PRAGMA foreign_keys = ON")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE DEFAULT NULL,
                phone_number TEXT DEFAULT NULL,
                is_active INTEGER DEFAULT 1,
                session_file TEXT UNIQUE NOT NULL
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS smm_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                photo TEXT DEFAULT NULL
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS hook_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL
            )
        """
        )
        await db.execute(
            """
                CREATE TABLE IF NOT EXISTS smm_voices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT NULL,
                    selected INTEGER DEFAULT 0,
                    path TEXT UNIQUE NOT NULL
                )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS parse_source (
                chat_id INTEGER PRIMARY KEY,
                chat_title TEXT NOT NULL,
                chat_username TEXT DEFAULT NULL,
                chat_type TEXT NOT NULL,
                invite_hash TEXT DEFAULT NULL
            )
        """
        )
        try:
            await db.execute("ALTER TABLE parse_source ADD COLUMN invite_hash TEXT DEFAULT NULL")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE smm_messages ADD COLUMN msg_order INTEGER DEFAULT 1")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE smm_voices ADD COLUMN msg_order INTEGER DEFAULT 1")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE smm_voices ADD COLUMN used_for_replies INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS trigger_phrases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reply_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                photo TEXT DEFAULT NULL
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS trigger_auto_replies (
                session_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                replied_at TEXT NOT NULL,
                PRIMARY KEY (session_id, user_id)
            )
        """
        )
        # user_status is a 3-bit field (0-7):
        #   0: 000 - user written by himself
        #   1: 001 - answer to above user
        #   2: 010 - old dialog from session
        #   3: 011 - answer above user
        #   4: 100 - user from parsing
        #   5: 101 - user from parsing and mailed
        #   6: 110 - user added from search
        #   7: 111 - dialog with above user
        #      |||
        #      ||+------ user wait for mail - 0 or we answered for user - 1
        #      |+------- work with existing dialog - 1, event adding - 0
        #      +-------- user wrote himself - 0 we add user - 1
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT NULL,
                first_name TEXT DEFAULT NULL,
                last_name TEXT DEFAULT NULL,
                phone_number TEXT DEFAULT NULL,
                profile_photo_id INTEGER DEFAULT NULL,
                profile_photo TEXT DEFAULT NULL,
                user_status INTEGER NOT NULL DEFAULT 0,
                sended INTEGER NOT NULL DEFAULT 0,
                source_chat_id INTEGER DEFAULT NULL,
                source_post_id INTEGER DEFAULT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_chat_id) REFERENCES parse_source(chat_id)
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER,
                session_id INTEGER,
                is_read INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, session_id)
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                text TEXT DEFAULT NULL,
                attachment TEXT DEFAULT NULL,
                attachment_type TEXT DEFAULT NULL,
                chat_id INTEGER NOT NULL,
                is_out INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (message_id, chat_id),
                FOREIGN KEY (chat_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """
        )
        await db.execute(
            """
                CREATE TRIGGER IF NOT EXISTS delete_messages_if_user_does_not_exist
                AFTER DELETE ON users
                BEGIN
                    DELETE FROM messages
                    WHERE chat_id = OLD.user_id;
                END;
            """
        )
        try:
            await db.execute("ALTER TABLE messages ADD COLUMN origin TEXT DEFAULT 'manual'")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN origin TEXT DEFAULT NULL")
            await db.commit()
        except Exception:
            pass
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_access (
                chat_id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                has_access INTEGER NOT NULL,
                checked_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, session_id),
                FOREIGN KEY (chat_id) REFERENCES parse_source(chat_id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """
        )
        # Per-account address book registry for contact mailing. Deliberately
        # FK-free (same rationale as trigger_auto_replies): keyed by the
        # sending account's Telegram id (sessions.user_id), so the "already
        # messaged this contact" facts survive a session being deleted and
        # re-added. status: 'pending' | 'sent' | 'failed'. in_address_book is
        # refreshed on every import run - a contact removed from the account's
        # Telegram address book keeps its row (still reachable via the cached
        # access_hash) but drops to 0.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS account_contacts (
                account_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT DEFAULT NULL,
                display_name TEXT DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                in_address_book INTEGER NOT NULL DEFAULT 1,
                added_at TEXT NOT NULL,
                sent_at TEXT DEFAULT NULL,
                session_id INTEGER DEFAULT NULL,
                PRIMARY KEY (account_id, user_id)
            )
        """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_account_contacts_user ON account_contacts(user_id)"
        )

        await db.commit()

        return cls(db)

    @property
    def connection(self):
        return self._db

    async def closeConnection(self):
        await self._db.close()

    # ## ========================= Methods for sessions ======================== ###

    async def get_sessions(self) -> list:
        sessions = []
        async with self._lock:
            async with self._db.execute(
                """
                SELECT id, is_active, session_file, phone_number
                FROM sessions
            """
            ) as cursor:
                async for (
                    id,
                    is_active,
                    session_file,
                    phone_number,
                ) in cursor:
                    sessions.append(
                        {
                            "session_id": id,
                            "is_active": bool(is_active),
                            "session_file": session_file,
                            "phone_number": phone_number,
                        }
                    )
        return sessions

    async def add_new_session(self, session_file: str) -> str:
        async with self._lock:
            async with self._db.execute(
                """
                INSERT OR IGNORE INTO sessions (session_file)
                VALUES (?)
            """,
                (session_file,),
            ) as cursor:
                await self._db.commit()
                return str(cursor.lastrowid)

    async def delete_session(
        self, session_id: int, delete_mode: int
    ) -> list[int] | dict[int, list[int]]:
        user_ids: list[int] = []
        message_ids: dict[int, list[int]] = {}

        async with self._lock:
            async with self._db.execute(
                "SELECT user_id FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                account_id = row["user_id"] if row else None

            if delete_mode != 0:
                # Selecting the type of users to delete
                if delete_mode == 2:
                    sended_filter = "AND sended = 1"
                elif delete_mode == 3:
                    sended_filter = "AND sended = 0"
                else:
                    sended_filter = ""

                where_clause = f"""
                    WHERE user_id IN (
                        SELECT user_id
                        FROM user_sessions
                        WHERE session_id = ?
                    ) {sended_filter}
                """

                # Save users' ids to delete users' data
                async with self._db.execute(
                    f"""
                        SELECT user_id
                        FROM users
                        {where_clause}
                    """,
                    (session_id,),
                ) as cursor:
                    async for (user_id,) in cursor:
                        user_ids.append(user_id)

                await self._db.execute(
                    f"""
                        DELETE FROM users
                        {where_clause}
                    """,
                    (session_id,),
                )
            else:
                # Otherwise save messages' ids and connected
                # users ids to delete media files
                async with self._db.execute(
                    """
                        SELECT chat_id, message_id
                        FROM messages
                        WHERE session_id = ?
                    """,
                    (session_id,),
                ) as cursor:
                    async for (
                        chat_id,
                        message_id,
                    ) in cursor:
                        if chat_id not in message_ids:
                            message_ids[chat_id] = []
                        message_ids[chat_id].append(message_id)

            # Account contact registry. The same delete_mode taxonomy applies:
            # 1 -> whole book, 2 -> already-messaged (sent/failed), 3 -> pending.
            # Mode 0 ("keep") leaves it fully intact so a re-added account is
            # not re-messaged.
            if delete_mode != 0 and account_id is not None:
                if delete_mode == 2:
                    status_filter = "AND status != 'pending'"
                elif delete_mode == 3:
                    status_filter = "AND status = 'pending'"
                else:
                    status_filter = ""

                async with self._db.execute(
                    f"""
                        SELECT user_id FROM account_contacts
                        WHERE account_id = ? {status_filter}
                    """,
                    (account_id,),
                ) as cursor:
                    contact_user_ids = [row[0] async for row in cursor]

                await self._db.execute(
                    f"""
                        DELETE FROM account_contacts
                        WHERE account_id = ? {status_filter}
                    """,
                    (account_id,),
                )

                if contact_user_ids:
                    # GC contact identities no account references any more
                    # (messages cascade via FK + trigger). Parsed users keep
                    # their own origin and are untouched.
                    async with self._db.execute(
                        """
                        SELECT user_id FROM users
                        WHERE origin = 'contact'
                          AND user_id NOT IN (SELECT user_id FROM account_contacts)
                    """
                    ) as cursor:
                        orphan_ids = [row[0] async for row in cursor]
                    if orphan_ids:
                        await self._db.execute(
                            """
                            DELETE FROM users
                            WHERE origin = 'contact'
                              AND user_id NOT IN (SELECT user_id FROM account_contacts)
                        """
                        )
                        user_ids.extend(orphan_ids)

            await self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await self._db.commit()

        if delete_mode == 0:
            return message_ids
        else:
            return user_ids

    async def update_session(
        self, session_id: int, user_id: int, phone_number: str
    ) -> bool:
        is_new = None
        async with self._lock:
            async with self._db.execute(
                """
                SELECT user_id
                FROM sessions
                WHERE id = ?
            """,
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return False
                is_new = row["user_id"] is None
            await self._db.execute(
                """
                UPDATE sessions
                SET user_id = ?, phone_number = ?
                WHERE id = ?
            """,
                (user_id, phone_number, session_id),
            )
            await self._db.commit()
        return is_new

    async def get_session_user_id(self, session_id: int) -> int:
        async with self._lock:
            async with self._db.execute(
                """
                    SELECT user_id
                    FROM sessions
                    WHERE id = ?
                """,
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return row["user_id"] if row else 0

    # ## ==================== Methods for sending messages ===================== ###

    async def add_smm_message(self, text: str, photo: str, msg_order: int = 1) -> str:
        async with self._lock:
            async with self._db.execute(
                """
                INSERT INTO smm_messages (text, photo, msg_order)
                VALUES (?, ?, ?)
            """,
                (text if text else "", photo if photo else "", msg_order),
            ) as cursor:
                await self._db.commit()
                return str(cursor.lastrowid)

    async def edit_smm_message(
        self, id: int, text: str, photo: str, msg_order: int = 1
    ) -> str | None:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT photo FROM smm_messages WHERE id = ?
            """,
                (id,),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:
                return None

            await self._db.execute(
                """
                UPDATE smm_messages
                SET text = ?, photo = ?, msg_order = ?
                WHERE id = ?
            """,
                (text, photo or row["photo"] or None, msg_order, id),
            )
            await self._db.commit()

            return row["photo"]

    async def get_smm_messages(self) -> list:
        messages = []
        async with self._lock:
            async with self._db.execute(
                """
                SELECT id, text, photo, msg_order
                FROM smm_messages
            """
            ) as cursor:
                async for (
                    id,
                    text,
                    photo,
                    msg_order,
                ) in cursor:
                    messages.append(
                        {
                            "id": id,
                            "text": text if text else None,
                            "photo": photo if photo else None,
                            "order": msg_order or 1,
                        }
                    )
        return messages

    async def delete_smm_message(self, id: int) -> str | None:
        async with self._lock:
            async with self._db.execute(
                """
                    SELECT photo
                    FROM smm_messages
                    WHERE id = ?
                """,
                (id,),
            ) as cursor:
                row = await cursor.fetchone()

            await self._db.execute(
                """
                    DELETE FROM smm_messages
                    WHERE id = ?
                """,
                (id,),
            )

            await self._db.commit()

            return row["photo"] if row else None

    # ## ===================== Methods for hook messages ======================== ###

    async def get_hook_messages(self) -> list[dict]:
        messages = []
        async with self._lock:
            async with self._db.execute(
                "SELECT id, text FROM hook_messages ORDER BY id"
            ) as cursor:
                async for (id, text) in cursor:
                    messages.append({"id": id, "text": text})
        return messages

    async def add_hook_message(self, text: str) -> int:
        async with self._lock:
            async with self._db.execute(
                "INSERT INTO hook_messages (text) VALUES (?)", (text,)
            ) as cursor:
                await self._db.commit()
                return cursor.lastrowid

    async def delete_hook_message(self, id: int) -> None:
        async with self._lock:
            await self._db.execute("DELETE FROM hook_messages WHERE id = ?", (id,))
            await self._db.commit()

    async def update_hook_message(self, id: int, text: str) -> None:
        async with self._lock:
            await self._db.execute(
                "UPDATE hook_messages SET text = ? WHERE id = ?", (text, id)
            )
            await self._db.commit()

    # ## =================== Methods for trigger phrases ========================= ###

    async def get_trigger_phrases(self) -> list[dict]:
        phrases = []
        async with self._lock:
            async with self._db.execute(
                "SELECT id, text FROM trigger_phrases ORDER BY id"
            ) as cursor:
                async for (id, text) in cursor:
                    phrases.append({"id": id, "text": text})
        return phrases

    async def add_trigger_phrase(self, text: str) -> int:
        async with self._lock:
            async with self._db.execute(
                "INSERT INTO trigger_phrases (text) VALUES (?)", (text,)
            ) as cursor:
                await self._db.commit()
                return cursor.lastrowid

    async def delete_trigger_phrase(self, id: int) -> None:
        async with self._lock:
            await self._db.execute("DELETE FROM trigger_phrases WHERE id = ?", (id,))
            await self._db.commit()

    async def update_trigger_phrase(self, id: int, text: str) -> None:
        async with self._lock:
            await self._db.execute(
                "UPDATE trigger_phrases SET text = ? WHERE id = ?", (text, id)
            )
            await self._db.commit()

    # ## =================== Methods for reply messages =========================== ###

    async def add_reply_message(self, text: str, photo: str) -> str:
        async with self._lock:
            async with self._db.execute(
                """
                INSERT INTO reply_messages (text, photo)
                VALUES (?, ?)
            """,
                (text if text else "", photo if photo else ""),
            ) as cursor:
                await self._db.commit()
                return str(cursor.lastrowid)

    async def edit_reply_message(self, id: int, text: str, photo: str) -> str | None:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT photo FROM reply_messages WHERE id = ?
            """,
                (id,),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:
                return None

            await self._db.execute(
                """
                UPDATE reply_messages
                SET text = ?, photo = ?
                WHERE id = ?
            """,
                (text, photo or row["photo"] or None, id),
            )
            await self._db.commit()

            return row["photo"]

    async def get_reply_messages(self) -> list:
        messages = []
        async with self._lock:
            async with self._db.execute(
                """
                SELECT id, text, photo
                FROM reply_messages
            """
            ) as cursor:
                async for (id, text, photo) in cursor:
                    messages.append(
                        {
                            "id": id,
                            "text": text if text else None,
                            "photo": photo if photo else None,
                        }
                    )
        return messages

    async def delete_reply_message(self, id: int) -> str | None:
        async with self._lock:
            async with self._db.execute(
                """
                    SELECT photo
                    FROM reply_messages
                    WHERE id = ?
                """,
                (id,),
            ) as cursor:
                row = await cursor.fetchone()

            await self._db.execute(
                """
                    DELETE FROM reply_messages
                    WHERE id = ?
                """,
                (id,),
            )

            await self._db.commit()

            return row["photo"] if row else None

    # ## =================== Methods for trigger auto-reply dedup ================= ###

    async def has_trigger_replied(self, session_id: int, user_id: int) -> bool:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT 1 FROM trigger_auto_replies
                WHERE session_id = ? AND user_id = ?
                LIMIT 1
            """,
                (session_id, user_id),
            ) as cursor:
                return await cursor.fetchone() is not None

    async def mark_trigger_replied(self, session_id: int, user_id: int) -> None:
        async with self._lock:
            await self._db.execute(
                """
                INSERT OR IGNORE INTO trigger_auto_replies (session_id, user_id, replied_at)
                VALUES (?, ?, ?)
            """,
                (session_id, user_id, datetime.now(tz=timezone("UTC")).isoformat()),
            )
            await self._db.commit()

    # ## ===================== Methods for sending voices ======================= ###
    async def add_voice_message(
        self,
        name: str,
        description: str,
        path: str,
        selected: bool = False,
        msg_order: int = 1,
    ) -> str:
        async with self._lock:
            async with self._db.execute(
                """
                    INSERT INTO smm_voices (name, description, selected, path, msg_order)
                    VALUES (?, ?, ?, ?, ?)
                """,
                (name, description, int(selected), path, msg_order),
            ) as cursor:
                await self._db.commit()
                return str(cursor.lastrowid)

    async def get_voice_message(self, id: int) -> dict:
        async with self._lock:
            async with self._db.execute(
                """
                    SELECT name, description, selected, path, msg_order
                    FROM smm_voices
                    WHERE id = ?
                """,
                (id,),
            ) as cursor:
                row = await cursor.fetchone()
                return {
                    "name": row["name"],
                    "desc": row["description"],
                    "selected": bool(row["selected"]),
                    "path": str(SMM_VOICES / row["path"]),
                    "order": row["msg_order"] or 1,
                }

    async def get_voice_messages(self) -> list[dict]:
        voice_msgs = []
        async with self._lock:
            async with self._db.execute(
                """
                    SELECT id, name, description, selected, path, msg_order, used_for_replies
                    FROM smm_voices
                """,
            ) as cursor:
                async for (id, name, desc, selected, path, msg_order, used_for_replies) in cursor:
                    voice_msgs.append(
                        {
                            "id": id,
                            "name": name,
                            "desc": desc,
                            "selected": bool(selected),
                            "path": str(SMM_VOICES / path),
                            "order": msg_order or 1,
                            "used_for_replies": bool(used_for_replies),
                        }
                    )

        return voice_msgs

    async def get_voices_for_mailing(self) -> list:
        voices = []
        async with self._lock:
            async with self._db.execute(
                """
                    SELECT path, msg_order
                    FROM smm_voices
                    WHERE selected = 1
                """
            ) as cursor:
                async for (path, msg_order) in cursor:
                    voices.append({"path": path, "order": msg_order or 1})

        return voices

    async def get_reply_voice_pool(self) -> list:
        voices = []
        async with self._lock:
            async with self._db.execute(
                """
                    SELECT name, path
                    FROM smm_voices
                    WHERE used_for_replies = 1
                """
            ) as cursor:
                async for (name, path) in cursor:
                    voices.append({"name": name, "path": path})

        return voices

    async def toggle_voice_message_selection(self, id: int, selected: bool) -> bool:
        async with self._lock:
            async with self._db.execute(
                """
                    UPDATE smm_voices
                    SET selected = ?
                    WHERE id = ?
                """,
                (
                    int(selected),
                    id,
                ),
            ) as cursor:
                changed = cursor.rowcount > 0
                await self._db.commit()
                return changed

    async def toggle_voice_reply_usage(self, id: int, used: bool) -> bool:
        async with self._lock:
            async with self._db.execute(
                """
                    UPDATE smm_voices
                    SET used_for_replies = ?
                    WHERE id = ?
                """,
                (
                    int(used),
                    id,
                ),
            ) as cursor:
                changed = cursor.rowcount > 0
                await self._db.commit()
                return changed

    async def delete_voice_message(self, id: int) -> str | None:
        async with self._lock:
            async with self._db.execute(
                """
                    SELECT path
                    FROM smm_voices
                    WHERE id = ?
                """,
                (id,),
            ) as cursor:
                row = await cursor.fetchone()

            async with self._db.execute(
                """
                    DELETE FROM smm_voices
                    WHERE id = ?
                """,
                (id,),
            ) as cursor:
                changed = cursor.rowcount > 0
                await self._db.commit()
                if changed:
                    return row["path"]
                return None

    # ## ========================= Methods for messages ========================= ###

    async def get_messages_from_user(self, chat_id: str, session_id: int) -> list:
        messages = []
        async with self._lock:
            async with self._db.execute(
                """
                    SELECT id, message_id, text, attachment, attachment_type, is_out, created_at
                    FROM messages
                    WHERE chat_id = ? AND session_id = ?
                    ORDER BY created_at ASC, message_id ASC
                """,
                (
                    chat_id,
                    session_id,
                ),
            ) as cursor:
                async for (
                    id,
                    message_id,
                    text,
                    attachment,
                    attachment_type,
                    is_out,
                    created_at,
                ) in cursor:
                    messages.append(
                        {
                            "id": id,
                            "message_id": message_id,
                            "text": text,
                            "attachment": attachment,
                            "attachment_type": attachment_type,
                            "is_out": bool(is_out),
                            "created_at": datetime.fromisoformat(created_at)
                            .astimezone(tzlocal.get_localzone())
                            .strftime("%d.%m.%Y %H:%M:%S"),
                        }
                    )
        return messages

    async def get_last_sync_message_id(self, session_id: int, user_id: int) -> int:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT MAX(message_id) AS last_id
                FROM messages
                WHERE session_id = ? AND chat_id = ?
            """,
                (session_id, user_id),
            ) as cursor:
                row = await cursor.fetchone()
                return row["last_id"] if row["last_id"] else 0

    async def add_new_message(
        self,
        message_id: int,
        text: str,
        attachment: str,
        attachment_type: str,
        chat_id: int,
        is_out: bool,
        session_id: int,
        created_at: str = datetime.now(tz=timezone("UTC")).isoformat(),
        origin: str = "manual",
    ) -> None:
        async with self._lock:
            await self._db.execute(
                """
                INSERT OR IGNORE INTO messages (message_id,
                                                text,
                                                attachment,
                                                attachment_type,
                                                chat_id,
                                                is_out,
                                                session_id,
                                                created_at,
                                                origin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    message_id,
                    text,
                    attachment,
                    attachment_type,
                    chat_id,
                    int(is_out),
                    session_id,
                    created_at,
                    origin,
                ),
            )
            await self._db.commit()

    async def has_outgoing_message(self, chat_id: int, session_id: int, origin: str) -> bool:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT 1 FROM messages
                WHERE chat_id = ? AND session_id = ? AND is_out = 1 AND origin = ?
                LIMIT 1
            """,
                (chat_id, session_id, origin),
            ) as cursor:
                return await cursor.fetchone() is not None

    # ## ====================== Methods for parse_source ======================= ###

    async def add_parse_source(
        self, chat_id: int, chat_title: str, chat_username: str, chat_type: str, invite_hash: str | None = None
    ) -> None:
        async with self._lock:
            await self._db.execute(
                """
                INSERT INTO parse_source (chat_id, chat_title, chat_username, chat_type, invite_hash)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    chat_title = excluded.chat_title,
                    chat_type = excluded.chat_type,
                    -- keep the known handle if this pass resolved the chat
                    -- without one (e.g. a ChannelForbidden stub from a
                    -- session with no access carries no username)
                    chat_username = COALESCE(excluded.chat_username, parse_source.chat_username),
                    invite_hash = COALESCE(excluded.invite_hash, parse_source.invite_hash)
            """,
                (chat_id, chat_title, chat_username, chat_type, invite_hash),
            )
            await self._db.commit()

    async def get_parse_source(self, chat_id: int) -> dict:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT chat_title, chat_username, chat_type, invite_hash
                FROM parse_source
                WHERE chat_id = ?
            """,
                (chat_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "chat_title": row["chat_title"],
                        "chat_username": row["chat_username"],
                        "chat_type": row["chat_type"],
                        "invite_hash": row["invite_hash"],
                    }
                else:
                    return {}

    async def get_unclassified_parse_sources(self) -> list[dict]:
        """Rows whose chat_type predates access-aware classification (legacy
        'unknown'/other garbage values) - candidates for the one-time repair."""
        placeholders = ", ".join("?" for _ in KNOWN_CHAT_TYPES)
        async with self._lock:
            async with self._db.execute(
                f"""
                SELECT chat_id, chat_title, chat_username, chat_type, invite_hash
                FROM parse_source
                WHERE chat_type NOT IN ({placeholders})
            """,
                tuple(KNOWN_CHAT_TYPES),
            ) as cursor:
                return [
                    {
                        "chat_id": row["chat_id"],
                        "chat_title": row["chat_title"],
                        "chat_username": row["chat_username"],
                        "chat_type": row["chat_type"],
                        "invite_hash": row["invite_hash"],
                    }
                    async for row in cursor
                ]

    async def update_parse_source_type(self, chat_id: int, chat_type: str) -> None:
        async with self._lock:
            await self._db.execute(
                "UPDATE parse_source SET chat_type = ? WHERE chat_id = ?",
                (chat_type, chat_id),
            )
            await self._db.commit()

    async def get_all_parse_sources(self) -> list[dict]:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT chat_id, chat_title, chat_username, chat_type, invite_hash
                FROM parse_source
            """
            ) as cursor:
                return [
                    {
                        "chat_id": row["chat_id"],
                        "chat_title": row["chat_title"],
                        "chat_username": row["chat_username"],
                        "chat_type": row["chat_type"],
                        "invite_hash": row["invite_hash"],
                    }
                    async for row in cursor
                ]

    async def update_parse_source_meta(
        self, chat_id: int, chat_title: str, chat_username: str | None, chat_type: str
    ) -> None:
        async with self._lock:
            await self._db.execute(
                """
                UPDATE parse_source
                SET chat_title = ?, chat_username = ?, chat_type = ?
                WHERE chat_id = ?
            """,
                (chat_title, chat_username, chat_type, chat_id),
            )
            await self._db.commit()

    async def clear_chat_access_denials(self, chat_id: int) -> int:
        """Drop the negative (has_access=0) chat_access rows for a chat.

        Those rows are only meaningful for a genuinely membership-gated
        chat. Once a chat is known to have a public @username every session
        can reach it by that handle regardless of membership, so a stale
        "no access" verdict there just permanently benches sessions the
        mailer would otherwise use."""
        async with self._lock:
            cursor = await self._db.execute(
                "DELETE FROM chat_access WHERE chat_id = ? AND has_access = 0",
                (chat_id,),
            )
            await self._db.commit()
            return cursor.rowcount

    # ## ======================= Methods for chat_access ========================= ###
    #
    # Both facts are stored ("session X can/cannot reach chat Y"), keyed by
    # (chat_id, session_id). A missing row means "never tested" - the vast
    # majority of chats are public and every session that ever touches one
    # succeeds immediately, so nothing is ever written for them. Rows only
    # accumulate for genuinely restricted chats, and even in the worst case
    # that's bounded by (private chats) x (number of Telegram accounts the
    # app manages) - a small, fixed number, not by user/message count. The
    # point of keeping the negative half (not just "confirmed accessible")
    # is that without it, a session that will never have access to a given
    # private group re-fails against it on every single mailing run
    # forever, instead of once.

    async def set_chat_access(self, chat_id: int, session_id: int, has_access: bool) -> None:
        async with self._lock:
            await self._db.execute(
                """
                INSERT INTO chat_access (chat_id, session_id, has_access, checked_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id, session_id) DO UPDATE SET
                    has_access = excluded.has_access,
                    checked_at = excluded.checked_at
            """,
                (chat_id, session_id, int(has_access), datetime.now(tz=timezone("UTC")).isoformat()),
            )
            await self._db.commit()

    async def get_chat_access(self, chat_ids: list[int]) -> dict[int, dict[int, bool]]:
        """Bulk-load known access (chat_id -> {session_id: has_access, ...})
        for a batch of chats in one query, so callers can preload once per
        mailing run instead of querying per user."""
        if not chat_ids:
            return {}
        result: dict[int, dict[int, bool]] = {}
        placeholders = ", ".join("?" for _ in chat_ids)
        async with self._lock:
            async with self._db.execute(
                f"""
                SELECT chat_id, session_id, has_access FROM chat_access
                WHERE chat_id IN ({placeholders})
            """,
                tuple(chat_ids),
            ) as cursor:
                async for row in cursor:
                    result.setdefault(row["chat_id"], {})[row["session_id"]] = bool(row["has_access"])
        return result

    async def get_chat_access_sessions(self, chat_ids: list[int]) -> dict[int, list[dict]]:
        """For each of the given chat_ids, the still-existing sessions
        confirmed to have access - joined against `sessions` so a session
        that's since been deleted is simply absent, no separate check
        needed."""
        if not chat_ids:
            return {}
        result: dict[int, list[dict]] = {}
        placeholders = ", ".join("?" for _ in chat_ids)
        async with self._lock:
            async with self._db.execute(
                f"""
                SELECT ca.chat_id, s.id AS session_id, s.session_file, s.phone_number
                FROM chat_access ca
                JOIN sessions s ON s.id = ca.session_id
                WHERE ca.chat_id IN ({placeholders}) AND ca.has_access = 1
            """,
                tuple(chat_ids),
            ) as cursor:
                async for row in cursor:
                    result.setdefault(row["chat_id"], []).append(
                        {
                            "session_id": row["session_id"],
                            "session_file": row["session_file"],
                            "phone_number": row["phone_number"],
                        }
                    )
        return result

    # ## ======================== Methods for users ============================ ###

    async def get_users_from_session(self, session_id: int) -> list:
        users = []
        async with self._lock:
            async with self._db.execute(
                """
                SELECT u.user_id, u.first_name, u.last_name, u.profile_photo, u.username, u.user_status,
                       m.text, m.created_at
                FROM users u
                JOIN user_sessions us ON u.user_id = us.user_id
                LEFT JOIN (
                    SELECT msg1.chat_id, msg1.text, msg1.created_at
                    FROM messages msg1
                    JOIN (
                        SELECT chat_id, MAX(created_at) AS max_created
                        FROM messages
                        WHERE session_id = ?
                        GROUP BY chat_id
                    ) msg2 ON msg1.chat_id = msg2.chat_id AND msg1.created_at = msg2.max_created
                    WHERE msg1.session_id = ?
                ) m ON u.user_id = m.chat_id
                WHERE us.session_id = ?
                GROUP BY u.user_id
                ORDER BY m.created_at DESC
            """,
                (session_id, session_id, session_id),
            ) as cursor:
                async for (
                    user_id,
                    first_name,
                    last_name,
                    profile_photo,
                    username,
                    status,
                    text,
                    created_at,
                ) in cursor:
                    users.append(
                        {
                            "user_id": user_id,
                            "first_name": first_name or "",
                            "last_name": last_name or "",
                            "profile_photo": profile_photo,
                            "username": username,
                            "status": status,
                            "last_message": text[:30] if text else None,
                            "created_at": datetime.fromisoformat(created_at)
                            .astimezone(tzlocal.get_localzone())
                            .strftime("%d.%m.%Y %H:%M:%S")
                            if created_at
                            else None,
                        }
                    )
        return users

    async def add_new_user(
        self,
        user_id: int,
        username: str,
        first_name: str,
        last_name: str,
        phone_number: str,
        profile_photo_id: int | None = None,
        profile_photo: str | None = None,
        user_status: int | None = None,
        sended: bool = False,
        source_chat_id: int | None = None,
        source_post_id: int | None = None,
    ) -> None:
        async with self._lock:
            await self._db.execute(
                """
                INSERT OR IGNORE INTO users (user_id,
                                             username,
                                             first_name,
                                             last_name,
                                             phone_number,
                                             profile_photo_id,
                                             profile_photo,
                                             user_status,
                                             sended,
                                             source_chat_id,
                                             source_post_id,
                                             created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    user_id,
                    username,
                    first_name,
                    last_name,
                    phone_number,
                    profile_photo_id,
                    profile_photo,
                    user_status,
                    int(sended),
                    source_chat_id,
                    source_post_id,
                    datetime.now(tz=timezone("UTC")).isoformat(),
                ),
            )
            await self._db.commit()

    async def add_user_to_session(self, user_id: int, session_id: int) -> bool:
        async with self._lock:
            async with self._db.execute(
                """
                INSERT OR IGNORE INTO user_sessions (user_id, session_id)
                VALUES (?, ?)
            """,
                (user_id, session_id),
            ) as cursor:
                inserted = cursor.rowcount > 0
                await self._db.commit()
                return inserted

    async def get_unread_dialogs(self) -> dict:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT user_id, session_id
                FROM user_sessions
                WHERE is_read = 0
            """
            ) as cursor:
                return {
                    (user_id, session_id): False
                    async for (user_id, session_id) in cursor
                }

    async def write_unread_dialogs(self, dialogs: dict):
        async with self._lock:
            for (user_id, session_id), was_read in dialogs.items():
                await self._db.execute(
                    """
                    UPDATE user_sessions
                    SET is_read = ?
                    WHERE user_id = ? AND session_id = ?
                """,
                    (int(was_read), user_id, session_id),
                )
            await self._db.commit()

    async def delete_user_from_session(self, user_id: int, session_id: int) -> str:
        profile_photo = ""
        async with self._lock:
            async with self._db.execute(
                """
                SELECT profile_photo
                FROM users
                WHERE user_id = ?
            """,
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                profile_photo = row["profile_photo"] or ""
            await self._db.execute(
                """
                DELETE FROM user_sessions
                WHERE user_id = ? AND session_id = ?
            """,
                (user_id, session_id),
            )
            await self._db.commit()
        return profile_photo

    async def check_user_presense(self, user_id: int) -> int:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT COUNT(*) as presense
                FROM users
                WHERE user_id = ?
            """,
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return row["presense"] or 0

    async def get_users_for_sending(self) -> list[dict]:
        users = []
        async with self._lock:
            async with self._db.execute(
                """
                SELECT user_id, username, user_status, source_chat_id, source_post_id
                FROM users
                WHERE sended = 0
                  AND user_id NOT IN (SELECT user_id FROM account_contacts)
                ORDER BY created_at ASC
            """
            ) as cursor:
                async for (
                    user_id,
                    username,
                    user_status,
                    source_chat_id,
                    source_post_id,
                ) in cursor:
                    users.append(
                        {
                            "user_id": user_id,
                            "username": username,
                            "user_status": user_status,
                            "source_chat_id": source_chat_id,
                            "source_post_id": source_post_id,
                        }
                    )
        return users

    async def get_user_data(self, user_id):
        async with self._lock:
            async with self._db.execute(
                """
                SELECT first_name, last_name, profile_photo
                FROM users
                WHERE user_id = ?
            """,
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return (row["first_name"], row["last_name"], row["profile_photo"])

    async def set_user_to_sended(self, user_id: int) -> None:
        async with self._lock:
            await self._db.execute(
                """
                UPDATE users
                SET sended = 1, user_status = user_status | 1
                WHERE user_id = ?
            """,
                (user_id,),
            )
            await self._db.commit()

    async def reset_parsed_to_sended(self) -> int:
        async with self._lock:
            cursor = await self._db.execute("UPDATE users SET sended = 1 WHERE sended = 0")
            await self._db.commit()
            return cursor.rowcount

    async def delete_unsended_parsed(self) -> int:
        async with self._lock:
            cursor = await self._db.execute("DELETE FROM users WHERE sended = 0")
            await self._db.commit()
            return cursor.rowcount

    async def get_user_photo(self, user_id: int):
        async with self._lock:
            async with self._db.execute(
                """
                SELECT profile_photo
                FROM users
                WHERE user_id = ?
            """,
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return row["profile_photo"] if row else None

    # ## ====================== Methods for account contacts =================== ###

    async def bulk_add_contacts(
        self, account_id: int, session_id: int, contacts: list[dict]
    ) -> None:
        """Import one session's address book in a single transaction.

        Lightweight: identities land in `users` (origin='contact', sended=1 so
        they never leak into the parsed-DB mailing), no profile photo fetch.
        Every run first marks the whole account's book as out-of-book, then the
        upsert flips the ones still present back to in_address_book=1; rows for
        removed contacts stay (status/sent_at untouched) at in_address_book=0.
        """
        if not account_id:
            return
        now = datetime.now(tz=timezone("UTC")).isoformat()
        user_rows = [
            (
                c["user_id"],
                c.get("username"),
                c.get("first_name"),
                c.get("last_name"),
                c.get("phone_number"),
                now,
            )
            for c in contacts
        ]
        contact_rows = [
            (
                account_id,
                c["user_id"],
                c.get("username"),
                c.get("display_name"),
                now,
                session_id,
            )
            for c in contacts
        ]
        async with self._lock:
            await self._db.execute(
                "UPDATE account_contacts SET in_address_book = 0 WHERE account_id = ?",
                (account_id,),
            )
            if user_rows:
                await self._db.executemany(
                    """
                    INSERT OR IGNORE INTO users (user_id,
                                                 username,
                                                 first_name,
                                                 last_name,
                                                 phone_number,
                                                 user_status,
                                                 sended,
                                                 origin,
                                                 created_at)
                    VALUES (?, ?, ?, ?, ?, 0, 1, 'contact', ?)
                """,
                    user_rows,
                )
                await self._db.executemany(
                    """
                    INSERT INTO account_contacts (account_id,
                                                  user_id,
                                                  username,
                                                  display_name,
                                                  status,
                                                  in_address_book,
                                                  added_at,
                                                  session_id)
                    VALUES (?, ?, ?, ?, 'pending', 1, ?, ?)
                    ON CONFLICT(account_id, user_id) DO UPDATE SET
                        in_address_book = 1,
                        username = excluded.username,
                        display_name = excluded.display_name,
                        session_id = excluded.session_id
                """,
                    contact_rows,
                )
            await self._db.commit()

    async def get_contacts_for_sending(
        self, account_id: int, address_book_filter: str = "all"
    ) -> list[dict]:
        """Pending contacts for one account, oldest first.

        address_book_filter: 'current' -> only in_address_book = 1,
        'past' -> only in_address_book = 0, anything else -> no filter.
        """
        if not account_id:
            return []
        clause = ""
        if address_book_filter == "current":
            clause = "AND in_address_book = 1"
        elif address_book_filter == "past":
            clause = "AND in_address_book = 0"
        contacts = []
        async with self._lock:
            async with self._db.execute(
                f"""
                SELECT user_id, username, display_name
                FROM account_contacts
                WHERE account_id = ? AND status = 'pending' {clause}
                ORDER BY added_at ASC
            """,
                (account_id,),
            ) as cursor:
                async for (user_id, username, display_name) in cursor:
                    contacts.append(
                        {
                            "user_id": user_id,
                            "username": username,
                            "display_name": display_name,
                        }
                    )
        return contacts

    async def get_sent_contact_user_ids(self) -> set[int]:
        """Every contact any account has already messaged - used to skip
        overlapping contacts when cross-account sending is disabled."""
        async with self._lock:
            async with self._db.execute(
                "SELECT DISTINCT user_id FROM account_contacts WHERE status = 'sent'"
            ) as cursor:
                return {row[0] async for row in cursor}

    async def set_contact_status(
        self, account_id: int, user_id: int, status: str
    ) -> None:
        sent_at = (
            datetime.now(tz=timezone("UTC")).isoformat() if status == "sent" else None
        )
        async with self._lock:
            await self._db.execute(
                """
                UPDATE account_contacts
                SET status = ?, sent_at = COALESCE(?, sent_at)
                WHERE account_id = ? AND user_id = ?
            """,
                (status, sent_at, account_id, user_id),
            )
            await self._db.commit()
