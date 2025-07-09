import aiosqlite
import sqlite3
import asyncio
from datetime import datetime
import os
import tzlocal
from pytz import timezone

from core.paths import DATABASE

DB_PATH = DATABASE / 'database.db'

class Database:
    def __init__(self, db):
        self._db = db
        self._lock = asyncio.Lock()

    @classmethod
    async def create(cls):
        
        if not os.path.exists(DB_PATH):
            open(DB_PATH, "a").close()

        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = sqlite3.Row # for mapping rows

        await db.execute("PRAGMA foreign_keys = ON")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE DEFAULT NULL,
                phone_number TEXT DEFAULT NULL,
                is_active INTEGER DEFAULT 1,
                session_file TEXT UNIQUE NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS smm_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                photo TEXT DEFAULT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS parse_source (
                chat_id INTEGER PRIMARY KEY,
                chat_title TEXT NOT NULL,
                chat_username TEXT DEFAULT NULL,
                chat_type TEXT NOT NULL
            )
        """)
        await db.execute("""
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
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER,
                session_id INTEGER,
                is_read INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, session_id)
            )
        """)
        await db.execute("""
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
        """)

        # await db.execute("""
        #     CREATE TABLE IF NOT EXISTS unread_dialogs (
        #         id INTEGER PRIMARY KEY AUTOINCREMENT,
        #         user_id INTEGER NOT NULL,
        #         session_id INTEGER NOT NULL,
        #         is_read INTEGER DEFAULT 0,
        #         FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        #         FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        #     )
        # """)

        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS delete_user_if_no_sessions
            AFTER DELETE ON user_sessions
            BEGIN
                DELETE FROM users
                WHERE user_id = OLD.user_id
                AND NOT EXISTS (
                    SELECT 1 FROM user_sessions WHERE user_id = OLD.user_id
                );
            END;
        """)

        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS delete_messages_if_user_has_no_sessions
            AFTER DELETE ON user_sessions
            BEGIN
                DELETE FROM messages
                WHERE chat_id = OLD.user_id
                AND NOT EXISTS (
                    SELECT 1 FROM user_sessions WHERE user_id = OLD.user_id
                );
            END;
        """)

        await db.commit()

        return cls(db)

    @property
    def connection(self):
        return self._db

    async def closeConnetion(self):
        await self._db.close()

    
    ### ========================= Methods for sessions ======================== ###

    async def get_sessions(self) -> list:
        sessions = []
        async with self._lock:
            async with self._db.execute("""
                SELECT id, is_active, session_file, phone_number
                FROM sessions
            """) as cursor:
                async for (id, is_active, session_file, phone_number, ) in cursor:
                    sessions.append({
                        "session_id": id,
                        "is_active": bool(is_active),
                        "session_file": session_file,
                        "phone_number": phone_number
                    })
        return sessions


    async def get_session_info(self, session_id: int) -> str:
        print("\n\n\n\n\n\nGet session info\n\n\n\n")
        async with self._lock:
            async with self._db.execute("""
                SELECT session_file
                FROM sessions
                WHERE id = ?
            """, (session_id)) as cursor:
                row = await cursor.fetchone()
                return row['session_file']

    
    async def add_new_session(self, session_file: str) -> str:
        async with self._lock:
            async with self._db.execute("""
                INSERT OR IGNORE INTO sessions (session_file)
                VALUES (?)
            """, (session_file,)) as cursor:
                await self._db.commit()
                return str(cursor.lastrowid)


    async def delete_session(self, session_id: int) -> list:
        user_ids = []
        async with self._lock:
            async with self._db.execute("""
                SELECT user_id
                FROM user_sessions
                WHERE session_id = ?
            """, (session_id, )) as cursor:
                async for (user_id, ) in cursor:
                    user_ids.append(user_id)

            await self._db.execute("""
                DELETE FROM sessions WHERE id = ?
            """, (session_id,))
            
            await self._db.commit()

        return user_ids

        
    async def update_session(self, session_id: int, user_id: int, phone_number: str) -> bool:
        print(phone_number)
        is_new = None
        async with self._lock:
            async with self._db.execute("""
                SELECT user_id
                FROM sessions
                WHERE id = ?
            """, (session_id, )) as cursor:
                row = await cursor.fetchone()
                is_new = row['user_id'] is None 
            await self._db.execute("""
                UPDATE sessions
                SET user_id = ?, phone_number = ?
                WHERE id = ?
            """, (user_id, phone_number, session_id))
            await self._db.commit()
        return is_new


    ### ==================== Methods for sending messages ===================== ###

    async def add_smm_message(self, text: str, photo: str) -> str:
        async with self._lock:
            async with self._db.execute("""
                INSERT INTO smm_messages (text, photo)
                VALUES (?, ?)
            """, (
                    text if text else '',
                    photo if photo else ''
                )
            ) as cursor:
                await self._db.commit()
                return str(cursor.lastrowid)
            
            
    async def edit_smm_message(self, id: int, text: str, photo: str) -> str | None:
        async with self._lock:
            async with self._db.execute("""
                SELECT photo FROM smm_messages WHERE id = ?
            """, (id,)) as cursor:
                row = await cursor.fetchone()

            await self._db.execute("""
                UPDATE smm_messages
                SET text = ?, photo = ?
                WHERE id = ?
            """, (
                    text if text else '',
                    photo or row['photo'] or '',
                    id
                ) 
            )

            await self._db.commit()

            return row['photo']


    # async def get_smm_messages_amount() -> int:
    #     # db = get_db()
    #     async with self._lock:
    #         async with db.execute("""
    #             SELECT COUNT(1) AS amount
    #             FROM send_messages
    #         """) as cursor:
    #             row = await cursor.fetchone()
    #             return row['amount']


    async def get_smm_messages(self) -> list:
        messages = []
        async with self._lock:
            async with self._db.execute("""
                SELECT id, text, photo
                FROM smm_messages
            """) as cursor:
                async for (id, text, photo, ) in cursor:
                    messages.append({
                        "id": id,
                        "text": text if text else None,
                        "photo": photo if photo else None
                    })
        return messages

######################################################










#######################################################
    async def get_last_sync_message_id(self, session_id: int, user_id: int) -> int:
        async with self._lock:
            async with self._db.execute("""
                SELECT MAX(message_id) AS last_id
                FROM messages
                WHERE session_id = ? AND chat_id = ?
            """, (session_id, user_id)) as cursor:
                row = await cursor.fetchone()
                return row['last_id'] if row['last_id'] else 0


    async def delete_smm_message(self, id: int) -> str | None:
        async with self._lock:
            async with self._db.execute("""
                SELECT photo FROM smm_messages WHERE id = ?
            """, (id,)) as cursor:
                row = await cursor.fetchone()

            await self._db.execute("""
                DELETE FROM smm_messages
                WHERE id = ?
            """, (id,))

            await self._db.commit()

            return row['photo']


    async def delete_smm_messages() -> None:
        # db = get_db()
        async with self._lock:
            await db.execute("""
                DELETE FROM send_messages
            """)
            await db.commit()


    ### ========================= Methods for messages ========================= ###

    async def get_messages_from_user(self, chat_id: str, session_id: int) -> list:
        messages = []
        async with self._lock:
            async with self._db.execute("""
                SELECT id, message_id, text, attachment, attachment_type, is_out, created_at
                FROM messages
                WHERE chat_id = ? AND session_id = ?
                ORDER BY created_at ASC, message_id ASC
            """, (chat_id, session_id, )) as cursor:
                async for (id, message_id, text, attachment, attachment_type, is_out, created_at, ) in cursor:
                    messages.append({
                        "id": id,
                        "message_id": message_id,
                        "text": text,
                        "attachment": attachment,
                        "attachment_type": attachment_type,
                        "is_out": bool(is_out),
                        "created_at": datetime.fromisoformat(created_at).astimezone(tzlocal.get_localzone()).strftime('%d.%m.%Y %H:%M:%S')
                    })
        return messages

    async def get_all_users_dialogs() -> dict:
        # db = get_db()
        dialogs = {}
        async with self._lock:
            async with db.execute("""
                SELECT message_id, text, attachment, attachment_type, attachment_caption, chat_id, is_out, created_at
                FROM messages
            """) as cursor:
                async for (message_id, text, attachment, attachment_type, attachment_caption, chat_id, is_out, created_at, ) in cursor:
                    if chat_id not in dialogs:
                        dialogs[chat_id] = []
        
                    dialogs[chat_id].append({
                        "message_id": message_id,
                        "text": text,
                        "attachment": attachment,
                        "attachment_type": attachment_type,
                        "attachment_caption": attachment_caption,
                        "is_out": bool(is_out),
                        "created_at": datetime.fromisoformat(created_at).strftime('%d.%m.%Y %H:%M')
                    })
        return dialogs


    async def add_new_message(self, message_id: int, text: str, attachment: str, attachment_type: str, chat_id: int,
                                is_out: bool, session_id: int, created_at: str = datetime.now(tz=timezone('UTC')).isoformat()) -> None:
        async with self._lock:
            await self._db.execute("""
                INSERT OR IGNORE INTO messages (message_id, text, attachment, attachment_type, chat_id, is_out, session_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                    message_id,
                    text,
                    attachment,
                    attachment_type,
                    chat_id,
                    int(is_out),
                    session_id,
                    created_at
                )
            )
            await self._db.commit()
    

    async def get_chat_messages(chat_id: int) -> list:
        # db = get_db()
        messages = []
        async with self._lock:
            async with db.execute("""
                SELECT text, attachment, attachment_type, chat_id, sender_id, created_at 
                FROM messages
                WHERE chat_id = ?
            """, (chat_id,)) as cursor:
                async for (text, attachment, attachment_type, attachment_caption, sender_id, created_at, ) in cursor:
                    messages.append({
                        "text": text,
                        "attachment": attachment,
                        "attachment_type": attachment_type,
                        "attachment_caption": attachment_caption,
                        "sender_id": sender_id,
                        "created_at": datetime.fromisoformat(created_at).strftime('%d.%m.%Y %H:%M')
                    })
        return messages


    async def delete_chat_messages(chat_id: int) -> None:
        # db = get_db()
        async with self._lock:
            await db.execute("""
                DELETE FROM messages
                WHERE chat_id = ? 
            """, (chat_id,))
            await db.commit()


    ### ====================== Methods for blocked_users ====================== ###

    # async def add_blocked_user(user_id: int, banned_by: int) -> None:
    #     # db = get_db()
    #     async with self._lock:
    #         await db.execute("""
    #             INSERT INTO blocked_users (user_id, banned_by, ban_time)
    #             VALUES (?, ?, ?)
    #         """, (
    #             user_id,
    #             banned_by,
    #             datetime.now().isoformat()
    #         ))
    #         await db.commit()


    # async def get_blocked_users() -> list:
    #     # db = get_db()
    #     blocked_users = []
    #     async with self._lock:
    #         async with db.execute("""
    #             SELECT user_id, banned_by, ban_time
    #             FROM blocked_users
    #         """) as cursor:
    #             async for (user_id, banned_by, ban_time, ) in cursor:
    #                 blocked_users.append({
    #                     "user_id": user_id,
    #                     "banned_by": banned_by,
    #                     "ban_time": datetime.fromisoformat(ban_time).strftime('%d.%m.%Y %H:%M')
    #                 })
    #     return blocked_users


    # async def delete_blocked_user(user_id: int) -> None:
    #     # db = get_db()
    #     async with self._lock:
    #         await db.execute("""
    #             DELETE FROM blocked_users
    #             WHERE user_id = ?
    #         """, (user_id,))
    #         await db.commit()


    # async def delete_all_blocked_users() -> None:
    #     # db = get_db()
    #     async with self._lock:
    #         await db.execute("""
    #             DELETE FROM blocked_users
    #         """)
    #         await db.commit()


    ### ========================== Methods for accounts ======================= ###

    # async def add_work_account(user_id: int, session_file: str, is_active: int = 1) -> None:
    #     # db = get_db()
    #     async with self._lock:
    #         await db.execute("""
    #             INSERT INTO accounts (user_id, session_file, is_active, last_used)
    #             VALUES (?, ?, ?, ?)
    #         """, (
    #             user_id,
    #             session_file,
    #             is_active,
    #             datetime.now().isoformat()
    #         ))
    #         await db.commit()


    # async def delete_work_account(id: int) -> None:
    #     # db = get_db()
    #     async with self._lock:
    #         await db.execute("""
    #             DELETE FROM accounts
    #             WHERE id = ?
    #         """, (id,))
    #         await db.commit()

        
    # async def delete_all_work_accounts() -> None:
    #     # db = get_db()
    #     async with self._lock:
    #         await db.execute("""
    #             DELETE FROM accounts
    #         """)
    #         await db.commit()


    # async def get_all_work_accounts() -> list:
    #     # db = get_db()
    #     accounts = []
    #     async with self._lock:
    #         async with db.execute("""
    #             SELECT user_id, session_file, is_active, last_used
    #             FROM accounts
    #         """) as cursor:
    #             async for (user_id, session_file, is_active, last_used, ) in cursor:
    #                 accounts.append({
    #                     "user_id": user_id,
    #                     "session_file": session_file,
    #                     "is_active": is_active,
    #                     "last_used": last_used
    #                 })
    #     return accounts


    ### ====================== Methods for parse_source ======================= ###

    async def add_parse_source(self, chat_id: int, chat_title: str, chat_username: str, chat_type: str) -> None:
        async with self._lock:
            await self._db.execute("""
                INSERT OR IGNORE INTO parse_source (chat_id, chat_title, chat_username, chat_type)
                VALUES (?, ?, ?, ?)
            """, (
                chat_id,
                chat_title,
                chat_username,
                chat_type
            ))
            await self._db.commit()


    async def get_parse_sources() -> list:
        # db = get_db()
        parse_sources = []
        async with self._lock:
            async with db.execute("""
                SELECT chat_id, chat_title, chat_username, chat_type
                FROM parse_source
            """) as cursor:
                async for (chat_id, chat_title, chat_username, chat_type, ) in cursor:
                    parse_sources.append({
                        "chat_id": chat_id,
                        "chat_title": chat_title,
                        "chat_username": chat_username,
                        "chat_type": chat_type
                    })
        return parse_sources


    async def get_parse_source(self, chat_id: int) -> dict:
        async with self._lock:
            async with self._db.execute("""
                SELECT chat_title, chat_username, chat_type
                FROM parse_source
                WHERE chat_id = ?  
            """, (chat_id,)) as cursor:
                row = await cursor.fetchone()
                return {
                    "chat_title": row["chat_title"],
                    "chat_username": row["chat_username"],
                    "chat_type": row["chat_type"]
                }
    

    ### ======================== Methods for users ============================ ###

    async def get_users_from_session(self, session_id: int) -> list:
        users = []
        async with self._lock:
            async with self._db.execute("""
                SELECT u.user_id, u.first_name, u.last_name, u.profile_photo, m.text, m.created_at
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
            """, (session_id, session_id, session_id)) as cursor:
                async for (user_id, first_name, last_name, profile_photo, text, created_at, ) in cursor:
                    users.append({
                        "user_id": user_id,
                        "first_name": first_name or "",
                        "last_name": last_name or "",
                        "profile_photo": profile_photo,
                        "last_message": text[:30] if text else None,
                        "created_at": datetime.fromisoformat(created_at).astimezone(tzlocal.get_localzone()).strftime('%d.%m.%Y %H:%M:%S') if created_at else None
                    })
        return users


    async def get_all_users() -> list:
        # db = get_db()
        users = []
        async with self._lock:
            async with db.execute("""
                SELECT user_id, username, first_name, last_name, phone_number,
                user_status, source_chat_id, source_post_id, created_at
                FROM users
            """) as cursor:
                async for (user_id, username, first_name, last_name, phone_number,
                    user_status, source_chat_id, source_post_id, created_at, ) in cursor:
                    users.append({
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "last_name": last_name,
                        "phone_number": phone_number,
                        "user_status": user_status,
                        "source_chat_id": source_chat_id,
                        "source_post_id": source_post_id,
                        "created_at": datetime.fromisoformat(created_at).strftime('%d.%m.%Y %H:%M')
                    })
        return users


    async def get_user_status(user_id: int) -> int:
        # db = get_db()
        async with self._lock:
            async with db.execute("""
                SELECT user_status
                FROM users
                WHERE user_id = ?
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                # print("User status with getting message:")
                # print(row.keys())
                return row['user_status'] if row else -1


    async def update_user_status(user_id: int, status: int) -> None:
        # db = get_db()
        async with self._lock:
            await db.execute("""
                UPDATE users
                SET user_status = ?
                WHERE user_id = ?
            """, (status, user_id,))
            await db.commit()
            

    async def add_new_user(
        self, user_id: int, username: str, first_name: str, last_name: str,
        phone_number: str, profile_photo_id: int = None, profile_photo: str = None,
        user_status: int = 0, sended: int = 0, source_chat_id: int = None, source_post_id: int = None
    ) -> None:
        async with self._lock:
            await self._db.execute("""
                INSERT OR IGNORE INTO users (user_id, username, first_name,
                last_name, phone_number, profile_photo_id, profile_photo, user_status, sended, source_chat_id, source_post_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
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
                datetime.now(tz=timezone('UTC')).isoformat()
            ))
            await self._db.commit()


    async def add_user_to_session(self, user_id: int, session_id: int) -> bool:
        async with self._lock:
            async with self._db.execute("""
                INSERT OR IGNORE INTO user_sessions (user_id, session_id)
                VALUES (?, ?)
            """, (user_id, session_id)) as cursor:
                inserted = cursor.rowcount > 0
                await self._db.commit()
                return inserted


    async def get_unread_dialogs(self) -> dict:
        async with self._lock:
            async with self._db.execute("""
                SELECT user_id, session_id
                FROM user_sessions
                WHERE is_read = 0
            """) as cursor:
                return {(user_id, session_id): False async for (user_id, session_id) in cursor}

    
    async def write_unread_dialogs(self, dialogs: dict):
        async with self._lock:
            for (user_id, session_id), was_read in dialogs.items():
                await self._db.execute("""
                    UPDATE user_sessions
                    SET is_read = ?
                    WHERE user_id = ? AND session_id = ?
                """, (int(was_read), user_id, session_id))
            await self._db.commit()


    # async def write_unread_dialogs(self, user_id, session_id):
    #     async with self._lock:
    #         await self._db.execute("""
    #             UPDATE user_sessions
    #             SET is_read = 1
    #             WHERE user_id != ? AND session_id != ?
    #         """, (user_id, session_id))
    #         await self._db.commit()


    async def delete_user_from_session(self, user_id: int, session_id: int) -> str:
        profile_photo = None
        async with self._lock:
            async with self._db.execute("""
                SELECT profile_photo
                FROM users
                WHERE user_id = ?
            """, (user_id, )) as cursor:
                row = await cursor.fetchone()
                profile_photo = row['profile_photo'] or None
            await self._db.execute("""
                DELETE FROM user_sessions
                WHERE user_id = ? AND session_id = ?
            """, (user_id, session_id))
            await self._db.commit()
        return profile_photo


    async def check_user_presense(self, user_id: int) -> int:
        async with self._lock:
            async with self._db.execute("""
                SELECT COUNT(*) as presense
                FROM users
                WHERE user_id = ?
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row['presense'] or 0


    async def get_user_info(user_id: int) -> dict:
        # db = get_db()
        async with self._lock:
            async with db.execute("""
                SELECT username, first_name, last_name
                FROM users
                WHERE user_id = ?
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                return {
                    "username": row['username'] or '',
                    "first_name": row['first_name'] or '',
                    "last_name": row['last_name'] or ''
                }


    async def get_users_ids() -> list:
        # db = get_db()
        async with self._lock:
            async with db.execute("""
                SELECT user_id
                FROM users
            """) as cursor:
                row = await cursor.fetchall()
                return [id_elem['user_id'] for id_elem in row]


    async def get_users_for_sending(self) -> list[dict]:
        users = []
        async with self._lock:
            async with self._db.execute("""
                SELECT user_id, username, user_status, source_chat_id, source_post_id
                FROM users
                WHERE sended = 0
            """) as cursor:
                async for (user_id, username, user_status, source_chat_id, source_post_id, ) in cursor:
                    users.append({
                        "user_id": user_id,
                        "username": username,
                        "user_status": user_status,
                        "source_chat_id": source_chat_id,
                        "source_post_id": source_post_id
                    })
        return users


    async def set_user_to_sended(self, user_id: int) -> None:
        async with self._lock:
            await self._db.execute("""
                UPDATE users
                SET sended = 1, user_status = user_status | 1
                WHERE user_id = ?
            """, (user_id,))
            await self._db.commit()


    ### ==================== Universal methods ================================ ###

    async def get_statistic() -> dict:
        # db = get_db()
        statistic = {}
        async with self._lock:
            async with db.execute("""
                SELECT
                    (SELECT COUNT(1) FROM users) AS users_amount,
                    (SELECT COUNT(1) FROM parse_source) AS channels_amount,
                    (SELECT COUNT(1) FROM send_messages) AS smm_amount,
                    (SELECT COUNT(1) FROM blocked_users) AS blocked_amount,
                    (SELECT COUNT(1) FROM accounts) AS accounts_amount
            """) as cursor:
                row = await cursor.fetchone()
                statistic['users_amount'] = row['users_amount'] or 0
                statistic['channels_amount'] = row['channels_amount'] or 0
                statistic['smm_amount'] = row['smm_amount'] or 0
                statistic['blocked_amount'] = row['blocked_amount'] or 0
                statistic['accounts_amount'] = row['accounts_amount'] or 0
        return statistic


    async def get_users_with_dialogs() -> list[dict]:
        # db = get_db()
        users_with_dialogs = []
        async with self._lock:
            async with db.execute("""
                SELECT user_id, username, first_name, last_name
                FROM users
                WHERE user_id IN (
                    SELECT DISTINCT chat_id FROM messages
                )
            """) as cursor:
                async for (user_id, username, first_name, last_name, ) in cursor:
                    users_with_dialogs.append({
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "last_name": last_name
                    })
        return users_with_dialogs
