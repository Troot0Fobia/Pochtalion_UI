import asyncio
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from shutil import copyfile

import aiosqlite
import appdirs
import tzlocal
from pytz import timezone

from core.paths import DATABASE
from core.utils import resource_path

DB_PATH = DATABASE / "database.db"


class Database:

    def __init__(self, db):
        self._db = db
        self._lock = asyncio.Lock()

    @classmethod
    async def create(cls):
        # Путь к базе в .exe или локально
        source_db_path = resource_path(DB_PATH)
        # Путь для записи
        if hasattr(sys, "_MEIPASS"):
            app_name = "Pochtalion"
            user_data_dir = Path(appdirs.user_data_dir(app_name))
            user_data_dir.mkdir(parents=True, exist_ok=True)
            db_path = user_data_dir / "database.db"
            # Копируем базу в AppData, если отсутствует
            if not db_path.exists():
                copyfile(source_db_path, db_path)
        else:
            db_path = source_db_path

        if not DB_PATH.exists():
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
            CREATE TABLE IF NOT EXISTS parse_source (
                chat_id INTEGER PRIMARY KEY,
                chat_title TEXT NOT NULL,
                chat_username TEXT DEFAULT NULL,
                chat_type TEXT NOT NULL
            )
        """
        )
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

    # ## ==================== Methods for sending messages ===================== ###

    async def add_smm_message(self, text: str, photo: str) -> str:
        async with self._lock:
            async with self._db.execute(
                """
                INSERT INTO smm_messages (text, photo)
                VALUES (?, ?)
            """,
                (text if text else "", photo if photo else ""),
            ) as cursor:
                await self._db.commit()
                return str(cursor.lastrowid)

    async def edit_smm_message(self, id: int, text: str, photo: str) -> str | None:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT photo FROM smm_messages WHERE id = ?
            """,
                (id,),
            ) as cursor:
                row = await cursor.fetchone()

            await self._db.execute(
                """
                UPDATE smm_messages
                SET text = ?, photo = ?
                WHERE id = ?
            """,
                (text, photo or row["photo"] or None, id),
            )
            await self._db.commit()

            return row["photo"]

    async def get_smm_messages(self) -> list:
        messages = []
        async with self._lock:
            async with self._db.execute(
                """
                SELECT id, text, photo
                FROM smm_messages
            """
            ) as cursor:
                async for (
                    id,
                    text,
                    photo,
                ) in cursor:
                    messages.append(
                        {
                            "id": id,
                            "text": text if text else None,
                            "photo": photo if photo else None,
                        }
                    )
        return messages

    async def delete_smm_message(self, id: int) -> str | None:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT photo FROM smm_messages WHERE id = ?
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

            return row["photo"]

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
                                                created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            await self._db.commit()

    # ## ====================== Methods for parse_source ======================= ###

    async def add_parse_source(
        self, chat_id: int, chat_title: str, chat_username: str, chat_type: str
    ) -> None:
        async with self._lock:
            await self._db.execute(
                """
                INSERT OR IGNORE INTO parse_source (chat_id, chat_title, chat_username, chat_type)
                VALUES (?, ?, ?, ?)
            """,
                (chat_id, chat_title, chat_username, chat_type),
            )
            await self._db.commit()

    async def get_parse_source(self, chat_id: int) -> dict:
        async with self._lock:
            async with self._db.execute(
                """
                SELECT chat_title, chat_username, chat_type
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
                    }
                else:
                    return {}

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
