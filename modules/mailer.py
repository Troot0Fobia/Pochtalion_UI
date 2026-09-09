import asyncio
import base64
import itertools
import json
import random
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from telethon.errors import (
    AuthKeyUnregisteredError,
    ChannelPrivateError,
    FloodWaitError,
    ForbiddenError,
    InputUserDeactivatedError,
    PeerFloodError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.errors.rpcerrorlist import MsgIdInvalidError, PeerIdInvalidError
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
from telethon.tl.types import ChatInviteAlready, InputPeerSelf, InputPeerUser, User

from core.logger import setup_logger
from core.paths import SMM_IMAGES, SMM_VOICES
from modules.client_wrapper import ClientWrapper, format_spam_status_notification

UPDATE_DELAY = 1
RESOLVE_BATCH_SIZE = 5
RESOLVE_DELAY = 1
SPAMBOT_CHECK_FLOOD_THRESHOLD = 900  # seconds; only check @SpamBot on long flood waits


class Mailer:

    def __init__(self, main_window):
        self.main_window = main_window
        self._running = False
        self.update_task = None
        self.is_mail_from_usernames = None
        self.is_mail_from_contacts = None
        self.contact_address_book_filter = "all"
        self.mail_data = None
        self.delay_min = None
        self.delay_max = None
        self.enable_second_message = False
        self.second_delay_min = None
        self.second_delay_max = None
        self.logger = setup_logger("Pochtalion.Mailer", "mailer.log")

    @dataclass
    class SessionWrapperInfo:
        wrapper: ClientWrapper
        was_started: bool
        session_id: int
        sent_count: int = 0

    @staticmethod
    def _resolve_delay_bounds(raw_min: str, raw_max: str) -> tuple[str, str]:
        resolved_min = raw_min or raw_max
        resolved_max = raw_max or resolved_min
        return resolved_min, resolved_max

    async def start(self, mail_data_str):
        self.logger.info("Mailing starting")
        mail_data = json.loads(mail_data_str)
        mail_type = mail_data.get(
            "mail_type",
            "usernames" if mail_data.get("is_parse_usernames") else "db",
        )
        self.is_mail_from_usernames = mail_type == "usernames"
        self.is_mail_from_contacts = mail_type == "contacts"
        self.contact_address_book_filter = mail_data.get("contact_filter", "all")
        self.is_send_text_messages = mail_data["is_send_text"]
        self.delay_min, self.delay_max = self._resolve_delay_bounds(
            mail_data["delay_min"], mail_data["delay_max"]
        )
        self.enable_second_message = bool(mail_data.get("enable_second_message"))
        if self.enable_second_message:
            self.second_delay_min, self.second_delay_max = self._resolve_delay_bounds(
                mail_data.get("second_delay_min", ""), mail_data.get("second_delay_max", "")
            )
        self.mailing_order = mail_data.get("order", "oldest_first")
        self.session_files = mail_data["selected_sessions"]
        self.session_wrappers = []
        self.mail_data: deque = deque()
        self._access_cache: dict[int, dict[int, bool]] = {}  # chat_id -> {session_id: has_access}, persisted
        self._participants_cache: dict[tuple[int, int], dict[int, User]] = {}  # (session_id, chat_id) -> {user_id: User}
        self._unreached_chats: dict[int, int] = {}  # chat_id -> number of users we couldn't resolve an entity for
        self._dialog_ids_cache: dict[int, set[int]] = {}  # session_id -> {entity_id} from one dialog scan per run
        self._undeliverable = 0  # resolved users the send was permanently rejected for (privacy / min entity / deleted)

        if self.is_send_text_messages:
            message_pool = await self.main_window.database.get_smm_messages()
        else:
            message_pool = await self.main_window.database.get_voices_for_mailing()
        self.first_messages = [m for m in message_pool if m.get("order", 1) != 2]
        self.second_messages = [m for m in message_pool if m.get("order") == 2]

        if not self.first_messages:
            self.logger.info("User doesn't provide mailing data")
            self.main_window.show_notification(
                "Внимание",
                f"Нет {'' if self.is_send_text_messages else 'голосовых'} сообщений для рассылки",
            )
            self.main_window.settings_bridge.finishMailing.emit()
            return

        if self.enable_second_message and not self.second_messages:
            self.logger.info("Second message enabled but no second messages available")
            self.main_window.show_notification(
                "Внимание", "Нет вторых сообщений для рассылки"
            )
            self.main_window.settings_bridge.finishMailing.emit()
            return

        if self.is_mail_from_usernames:
            if not mail_data["mailing_data"]:
                self.main_window.show_notification("Внимание", "Нет username'ов для рассылки")
                self.main_window.settings_bridge.finishMailing.emit()
                return
            for data in mail_data["mailing_data"].splitlines():
                matched = re.match(
                    r"^@?(?P<username>[a-zA-Z0-9_]{5,32})$", data.strip()
                )
                if matched:
                    self.mail_data.append({"username": matched.group("username")})
        elif self.is_mail_from_contacts:
            # Contacts are collected per session inside _run_contact_mailing()
            # after the sessions are started - nothing to preload here.
            pass
        else:
            users = await self.main_window.database.get_users_for_sending()
            if self.mailing_order == "newest_first":
                users.reverse()
            elif self.mailing_order == "random":
                random.shuffle(users)
            self.mail_data = deque(users)

        if not self.session_files:
            self.logger.info("User doesn't provide sessions")
            self.main_window.show_notification("Внимание", "Сессии не выбраны")
            self.main_window.settings_bridge.finishMailing.emit()
            return

        if not self.delay_min.isdigit() or not self.delay_max.isdigit():
            self.logger.info("User doesn't provide correct delay between messages")
            self.main_window.show_notification(
                "Внимание", "Неправильная задержка между сообщениями"
            )
            self.main_window.settings_bridge.finishMailing.emit()
            return

        if self.enable_second_message and (
            not self.second_delay_min.isdigit() or not self.second_delay_max.isdigit()
        ):
            self.logger.info("User doesn't provide correct delay before second message")
            self.main_window.show_notification(
                "Внимание", "Неправильная задержка перед вторым сообщением"
            )
            self.main_window.settings_bridge.finishMailing.emit()
            return

        if not self.mail_data and not self.is_mail_from_contacts:
            self.logger.info("User doesn't provide correct data, no data for mailing")
            self.main_window.show_notification(
                "Внимание", "Нет пользователей для рассылки"
            )
            self.main_window.settings_bridge.finishMailing.emit()
            return

        self.delay_min = int(self.delay_min or 0)
        self.delay_max = int(self.delay_max or 0)
        if self.delay_min > self.delay_max:
            self.delay_min, self.delay_max = self.delay_max, self.delay_min
        if self.enable_second_message:
            self.second_delay_min = int(self.second_delay_min or 0)
            self.second_delay_max = int(self.second_delay_max or 0)
            if self.second_delay_min > self.second_delay_max:
                self.second_delay_min, self.second_delay_max = (
                    self.second_delay_max,
                    self.second_delay_min,
                )
        self.logger.info(
            "Mailing config: sessions=%d, users=%d, delay=%d-%ds, second_message=%s, "
            "second_delay=%s, from_usernames=%s, msg_type=%s, smm_msgs=%d",
            len(self.session_files),
            len(self.mail_data),
            self.delay_min,
            self.delay_max,
            self.enable_second_message,
            f"{self.second_delay_min}-{self.second_delay_max}s" if self.enable_second_message else "n/a",
            self.is_mail_from_usernames,
            "text" if self.is_send_text_messages else "voice",
            len(self.first_messages) + len(self.second_messages),
        )
        self._running = True
        await self.start_sessions()

        index = 0
        self.sessions_count = len(self.session_wrappers)
        self.start_time = datetime.now()

        if self.is_mail_from_contacts:
            await self._run_contact_mailing()
            await self.stop()
            return

        self.update_task = asyncio.create_task(self.sendUpdate())
        self.total_users_count = len(self.mail_data)

        if self.is_mail_from_usernames:
            usernames = [data["username"] for data in list(self.mail_data)]
            resolved, failed_usernames = await self._resolve_usernames(usernames)
            self.mail_data = deque(resolved)
            if failed_usernames:
                self.logger.warning(
                    "Failed to resolve %d/%d username(s): %s",
                    len(failed_usernames), len(usernames), ", ".join(failed_usernames),
                )
                self.main_window.show_notification(
                    "Не удалось зарезолвить username",
                    f"Не найдены или недоступны на всех аккаунтах "
                    f"({len(failed_usernames)} из {len(usernames)}):\n"
                    + "\n".join(failed_usernames),
                )
        else:
            # One bulk query for every distinct source group referenced by
            # this run, instead of a lookup per user during the send loop -
            # most chats are public and won't have a single row here anyway.
            distinct_chat_ids = list(
                {u["source_chat_id"] for u in self.mail_data if u.get("source_chat_id") is not None}
            )
            self._access_cache = await self.main_window.database.get_chat_access(
                distinct_chat_ids
            )

        while self.mail_data:
            if not self._running or not self.session_wrappers:
                break

            smm_message = random.choice(self.first_messages)
            user_id = None
            index += 1

            entity = None
            if self.is_mail_from_usernames:
                entity, session_info = self.mail_data.popleft()
                if session_info not in self.session_wrappers:
                    self.logger.info(
                        "Session %s is no longer active, skipping user %s",
                        session_info.wrapper.session_file, entity.id,
                    )
                    continue
                user_id = entity.id
                await session_info.wrapper.process_new_user(
                    {
                        "user_id": user_id,
                        "first_name": getattr(entity, "first_name", None),
                        "last_name": getattr(entity, "last_name", None),
                        "username": getattr(entity, "username", None),
                        "phone_number": getattr(entity, "phone", None),
                    },
                    last_message=None,
                    user_status=4,
                )
            else:
                user_data = self.mail_data.popleft()
                session_info = self._select_session_for_user(user_data, index)
                if session_info is None:
                    self.logger.info(
                        "No selected session has access to user %s's source, skipping",
                        user_data.get("user_id"),
                    )
                    self._note_unreached(user_data.get("source_chat_id"))
                    continue
                entity = await self.get_user_entity(
                    user_data,
                    session_info.wrapper.client,
                    session_info.session_id,
                )
                if entity is None or not isinstance(entity, (InputPeerUser, InputPeerSelf)):
                    self.logger.info("No entity received from data")
                    self._note_unreached(user_data.get("source_chat_id"))
                    continue
                user_id = entity.user_id
                await self.main_window.database.add_user_to_session(
                    user_id, session_info.session_id
                )

            result = await self._send_single_message(
                session_info, user_id, self._build_message_payload(smm_message)
            )
            if result in ("skip", "undeliverable"):
                if result == "undeliverable":
                    self._undeliverable += 1
                continue
            if result == "ok" and not self.is_mail_from_usernames:
                await self.main_window.database.set_user_to_sended(user_id)

            await session_info.wrapper.process_new_user(
                entity, smm_message["text"] if self.is_send_text_messages else ""
            )
            session_info.sent_count += 1

            if self.enable_second_message:
                await asyncio.sleep(
                    random.uniform(self.second_delay_min, self.second_delay_max)
                )
                second_message = random.choice(self.second_messages)
                second_result = await self._send_single_message(
                    session_info, user_id, self._build_message_payload(second_message)
                )
                if second_result == "undeliverable":
                    self._undeliverable += 1
                if second_result not in ("skip", "undeliverable"):
                    await session_info.wrapper.process_new_user(
                        entity,
                        second_message["text"] if self.is_send_text_messages else "",
                    )
                    session_info.sent_count += 1

            await asyncio.sleep(random.uniform(self.delay_min, self.delay_max))

        await self.stop()

    def _build_message_payload(self, smm_message) -> dict:
        if self.is_send_text_messages:
            base64_file = None
            if smm_message["photo"]:
                with open(SMM_IMAGES / smm_message["photo"], "rb") as file:
                    base64_file = base64.b64encode(file.read()).decode("utf-8")

            return {
                "base64_file": base64_file,
                "text": smm_message["text"],
                "filename": smm_message["photo"],
            }
        return {"path": str(SMM_VOICES / smm_message["path"])}

    async def _send_single_message(self, session_info, user_id, message: dict) -> str:
        """Send one message to user_id via session_info.

        Returns "ok" on a genuine send, "flood" if a FloodWaitError was
        hit and absorbed (matches the historical behavior of proceeding
        as if the message went through after waiting out the flood),
        "undeliverable" if the user was resolved but Telegram permanently
        rejected the send (privacy settings, a min-entity access hash that
        is not valid for DMs, a deleted account), or "skip" if something
        unexpected went wrong and the caller should just abandon this user.
        """
        try:
            await session_info.wrapper.sendMessage(
                user_id, json.dumps(message), not self.is_send_text_messages, origin="mailer"
            )
            return "ok"
        except FloodWaitError as e:
            self.logger.error(
                f"Caught Flood Wait Error, wait for {e.seconds}", exc_info=True
            )
            self.main_window.show_notification(
                "Внимание",
                f"Сессия {session_info.wrapper.session_file} поймала флуд, ждем {e.seconds + 10} секунд",
            )
            if e.seconds >= SPAMBOT_CHECK_FLOOD_THRESHOLD:
                await self._check_spambot_status(session_info.wrapper)
            await asyncio.sleep(e.seconds + 10)
            return "flood"
        except PeerFloodError as e:
            self.logger.error(
                f"Caught Flood Error, stop mailing for this session {session_info.wrapper.session_file}: {e}",
                exc_info=True,
            )
            await self._check_spambot_status(session_info.wrapper)
            await self.finish_session(session_info.session_id)
            self.main_window.show_notification(
                "Внимание",
                f"Сессия {session_info.wrapper.session_file} поймала флуд",
            )
            return "skip"
        except InputUserDeactivatedError as e:
            self.logger.error(
                f"Caught User Deactivated Error, skip this user {user_id}: {e}",
                exc_info=True,
            )
            return "undeliverable"
        except ForbiddenError as e:
            self.logger.error(
                f"Caught Forbidden Error, skip this user {user_id}: {e}",
                exc_info=True,
            )
            return "undeliverable"
        except PeerIdInvalidError as e:
            # Almost always a `min` user pulled from a channel's participant
            # list: the access hash is only valid inside that channel, so a
            # direct message is rejected. Nothing to retry - the user simply
            # cannot be DMed by this account without a prior relationship.
            self.logger.warning(
                "PeerIdInvalid for user %s via %s - cannot DM (min entity / privacy): %s",
                user_id, session_info.wrapper.session_file, e,
            )
            return "undeliverable"
        except Exception:
            self.logger.error(
                "Unexpected error during message sending, session=%s, user_id=%s",
                session_info.wrapper.session_file, user_id, exc_info=True,
            )
            return "skip"

    async def _resolve_usernames(
        self, usernames: list[str]
    ) -> tuple[list[tuple], list[str]]:
        """Resolve usernames to entities, distributing batches across sessions.

        Each session attempts up to RESOLVE_BATCH_SIZE usernames before handing
        control to the next session. Usernames a session fails to resolve are
        handed off to the next session's batch instead of being retried
        repeatedly on the same (possibly rate-limited) session. A username is
        dropped only once every session has failed to resolve it. The session
        that resolves a username is kept attached to the entity, so it is later
        used to send the message too, since only that session's client has the
        resolved entity cached.
        """
        num_sessions = len(self.session_wrappers)
        if num_sessions == 0:
            return [], list(usernames)
        session_cycle = itertools.cycle(self.session_wrappers)
        flood_until: dict[int, float] = {}

        pending = deque((username, 0) for username in usernames)
        carry_over = deque()
        resolved = []
        failed_usernames = []
        seen_ids = set()
        skip_streak = 0

        while pending or carry_over:
            if not self._running:
                break

            session_info = next(session_cycle)
            loop_time = asyncio.get_event_loop().time()
            cooldown_until = flood_until.get(session_info.session_id, 0)
            if loop_time < cooldown_until:
                skip_streak += 1
                if skip_streak >= num_sessions:
                    await asyncio.sleep(1)
                    skip_streak = 0
                continue
            skip_streak = 0

            batch = []
            while carry_over and len(batch) < RESOLVE_BATCH_SIZE:
                batch.append(carry_over.popleft())
            while pending and len(batch) < RESOLVE_BATCH_SIZE:
                batch.append(pending.popleft())
            if not batch:
                break

            for i, (username, attempts) in enumerate(batch):
                try:
                    entity = await session_info.wrapper.client.get_entity(username)
                    if entity.id not in seen_ids:
                        seen_ids.add(entity.id)
                        resolved.append((entity, session_info))
                except FloodWaitError as e:
                    self.logger.warning(
                        f"Flood wait ({e.seconds}s) resolving '{username}' on session "
                        f"{session_info.wrapper.session_file}, handing off remaining "
                        f"batch to next session"
                    )
                    flood_until[session_info.session_id] = loop_time + e.seconds
                    for u, a in batch[i:]:
                        if a + 1 < num_sessions:
                            carry_over.append((u, a + 1))
                        else:
                            self.logger.error(
                                f"Giving up resolving '{u}', all sessions exhausted"
                            )
                            failed_usernames.append(u)
                    break
                except Exception as e:
                    if attempts + 1 < num_sessions:
                        carry_over.append((username, attempts + 1))
                    else:
                        self.logger.error(
                            f"Failed to resolve '{username}' on all {num_sessions} "
                            f"session(s), last error: {e}",
                            exc_info=True,
                        )
                        failed_usernames.append(username)

                await asyncio.sleep(RESOLVE_DELAY)

        return resolved, failed_usernames

    async def _run_contact_mailing(self) -> None:
        """Contact mailing: every session messages only its own Telegram
        address book, never another session's.

        Phase 1 imports each session's contacts into the DB (a kind of
        parsing - see Database.bulk_add_contacts). Phase 2 walks the pending
        rows per account and sends, reusing the shared send / flood-wait /
        second-message machinery. Dedup and the "overlapping contacts"
        setting are handled through account_contacts, keyed by the sending
        account's Telegram id, so history survives a session being removed
        and re-added.
        """
        db = self.main_window.database
        cross_send = bool(
            self.main_window.settings_manager.get_setting("contact_mailing_cross_send")
        )

        # ---- Phase 1: import address books ------------------------------------
        self.main_window.settings_bridge.renderMailingProgressData.emit(
            json.dumps(
                {
                    "status": "сбор контактов",
                    "total_count": "0/0",
                    "time": "00:00:00/00:00:00",
                }
            )
        )
        account_by_session: dict[int, int] = {}
        for session_info in list(self.session_wrappers):
            if not self._running:
                return
            wrapper = session_info.wrapper
            account_id = getattr(wrapper, "session_user_id", None) or (
                await db.get_session_user_id(session_info.session_id)
            )
            if not account_id:
                self.logger.warning(
                    "Session %s has no account id, skipping contact import",
                    wrapper.session_file,
                )
                continue
            account_by_session[session_info.session_id] = account_id
            try:
                result = await wrapper.client(GetContactsRequest(hash=0))
            except FloodWaitError as e:
                self.logger.error(
                    "Flood wait %ss fetching contacts for %s",
                    e.seconds, wrapper.session_file, exc_info=True,
                )
                self.main_window.show_notification(
                    "Внимание",
                    f"Сессия {wrapper.session_file}: флуд при сборе контактов "
                    f"({e.seconds}с), пропускаем",
                )
                continue
            except Exception:
                self.logger.error(
                    "Failed to fetch contacts for %s", wrapper.session_file,
                    exc_info=True,
                )
                continue

            contacts = [
                {
                    "user_id": u.id,
                    "username": u.username,
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                    "phone_number": u.phone,
                    "display_name": " ".join(
                        p for p in (u.first_name, u.last_name) if p
                    )
                    or None,
                }
                for u in getattr(result, "users", [])
                if not getattr(u, "is_self", False)
                and not u.bot
                and not u.deleted
            ]
            await db.bulk_add_contacts(
                account_id, session_info.session_id, contacts
            )
            self.logger.info(
                "Session %s: imported %d contacts",
                wrapper.session_file, len(contacts),
            )
            await asyncio.sleep(RESOLVE_DELAY)

        if not self._running:
            return

        # ---- Phase 2: send --------------------------------------------------
        blocked: set[int] = set()
        if not cross_send:
            blocked = await db.get_sent_contact_user_ids()

        queues: list[tuple] = []
        total = 0
        for session_info in self.session_wrappers:
            account_id = account_by_session.get(session_info.session_id)
            if not account_id:
                continue
            rows = await db.get_contacts_for_sending(
                account_id, self.contact_address_book_filter
            )
            if self.mailing_order == "newest_first":
                rows.reverse()
            elif self.mailing_order == "random":
                random.shuffle(rows)
            queues.append((session_info, account_id, rows))
            total += len(rows)

        if total == 0:
            self.main_window.show_notification(
                "Внимание", "Нет контактов для рассылки"
            )
            return

        self.total_users_count = total
        self.update_task = asyncio.create_task(self.sendUpdate())

        for session_info, account_id, rows in queues:
            for row in rows:
                if not self._running:
                    return
                if session_info not in self.session_wrappers:
                    break  # session died (e.g. PeerFlood) - abandon its queue
                user_id = row["user_id"]
                if not cross_send and user_id in blocked:
                    continue

                smm_message = random.choice(self.first_messages)
                result = await self._send_single_message(
                    session_info, user_id, self._build_message_payload(smm_message)
                )
                if result in ("ok", "flood"):
                    await db.set_contact_status(account_id, user_id, "sent")
                    blocked.add(user_id)
                    session_info.sent_count += 1

                    if self.enable_second_message:
                        await asyncio.sleep(
                            random.uniform(
                                self.second_delay_min, self.second_delay_max
                            )
                        )
                        second_message = random.choice(self.second_messages)
                        second_result = await self._send_single_message(
                            session_info,
                            user_id,
                            self._build_message_payload(second_message),
                        )
                        if second_result in ("ok", "flood"):
                            session_info.sent_count += 1
                elif session_info in self.session_wrappers:
                    # Session still alive -> the failure is on this contact
                    # (privacy / blocked / deactivated). Mark it so we don't
                    # retry every run; resetting means deleting the record.
                    await db.set_contact_status(account_id, user_id, "failed")
                else:
                    break

                await asyncio.sleep(
                    random.uniform(self.delay_min, self.delay_max)
                )

    async def _update_access(self, chat_id: int, session_id, has_access: bool) -> None:
        sid = int(session_id)
        await self.main_window.database.set_chat_access(chat_id, sid, has_access)
        self._access_cache.setdefault(chat_id, {})[sid] = has_access

    def _select_session_for_user(self, user_data, index):
        """Pick which session should resolve/send to this user.

        A resolved InputPeer's access_hash is only valid for the session
        that obtained it, so a user backed by a parsed source group can
        only be mailed through a session that actually has access to that
        group. Most chats are public and have no entry in _access_cache at
        all - any selected session is eligible and this is a plain round
        robin, same as before. Sessions confirmed accessible for this chat
        (from parsing or an earlier run) are preferred; sessions confirmed
        to lack access are avoided entirely, so a private group's dead-end
        sessions are only ever tried once, period - not once per run.
        Anything with no recorded status yet is tried via round robin so
        access can still be discovered.

        A user carrying a public @username is exempt from all of this:
        get_entity(username) resolves them on any session regardless of
        source-group membership, so gating them behind group access just
        strands them when the group happens to be private.
        """
        if user_data.get("username"):
            return self.session_wrappers[index % self.sessions_count]

        source_chat_id = user_data.get("source_chat_id")
        if source_chat_id is None:
            return self.session_wrappers[index % self.sessions_count]

        status = self._access_cache.get(source_chat_id)
        if not status:
            return self.session_wrappers[index % self.sessions_count]

        confirmed = [si for si in self.session_wrappers if status.get(int(si.session_id)) is True]
        if confirmed:
            return confirmed[index % len(confirmed)]

        untested = [si for si in self.session_wrappers if int(si.session_id) not in status]
        if untested:
            return untested[index % len(untested)]
        return None

    async def _get_group_participants(
        self, session_client, session_id, chat_entity, chat_id: int
    ) -> dict[int, "User"]:
        """One full participants scan per (session, group) per mailing run,
        cached and reused for every subsequent user from the same group
        instead of re-scanning the whole group from scratch for each one."""
        cache_key = (int(session_id), chat_id)
        if cache_key not in self._participants_cache:
            participants: dict[int, User] = {}
            async for user in session_client.iter_participants(chat_entity):
                participants[user.id] = user
            self._participants_cache[cache_key] = participants
        return self._participants_cache[cache_key]

    async def get_user_entity(self, user_data, session_client, session_id):
        user_id = user_data["user_id"]
        username = user_data["username"]
        source_chat_id = user_data["source_chat_id"]
        source_post_id = user_data["source_post_id"]

        # Username first: get_entity(username) returns a *full* entity that
        # can be DMed. The user-id cache lookup below is cheaper but can
        # hand back a `min` InputPeerUser cached from an earlier participant
        # scan this run - it passes the isinstance check yet the send later
        # fails with PeerIdInvalidError. Resolving the username up front
        # avoids that for every user that has one.
        if username:
            try:
                entity = await session_client.get_entity(username)
                input_entity = await session_client.get_input_entity(entity)
                if isinstance(input_entity, (InputPeerUser, InputPeerSelf)):
                    return input_entity
            except (UsernameNotOccupiedError, UsernameInvalidError, ValueError):
                # handle freed or changed since parsing - fall through
                pass
            except AuthKeyUnregisteredError:
                self.logger.error("Auth key unregistered for session %s", session_id, exc_info=True)
                return None
            except Exception as e:
                self.logger.warning(
                    f"Unexpected error while receiving user entity from username: {e}",
                    exc_info=True,
                )

        try:
            input_entity = await session_client.get_input_entity(user_id)
            if isinstance(input_entity, (InputPeerUser, InputPeerSelf)):
                return input_entity
            # Telethon's entity cache is keyed by raw numeric id with no
            # per-type namespace, so a user id that happens to numerically
            # collide with an already-cached chat/channel id can come back
            # as the wrong peer type here. Fall through to the other
            # resolution strategies instead of returning a mismatched peer.
        except ValueError:
            pass
        except AuthKeyUnregisteredError:
            self.logger.error("Auth key unregistered for session %s", session_id, exc_info=True)
            return None
        except Exception:
            self.logger.error(
                "Unexpected error resolving entity for user %s, session %s",
                user_id, session_id, exc_info=True,
            )
            return None

        source_data = await self.main_window.database.get_parse_source(source_chat_id)
        if not source_data:
            return None

        chat_username = source_data.get("chat_username")
        chat_type = source_data.get("chat_type")
        if chat_username:
            # Public sources are resolvable by username regardless of this
            # session's membership, so access history (measured against the
            # numeric identifier below) doesn't gate this path.
            chat_identifier = chat_username
        else:
            if chat_type in ("broadcast", "megagroup", "gigagroup"):
                # source_chat_id is stored as the raw (unmarked) Telethon
                # entity id. A bare positive int is always resolved by
                # Telethon as a PeerUser, never a channel, so it must be
                # marked as such here - matching the -100{id} convention
                # used elsewhere in the app (see client_wrapper.py).
                chat_identifier = int(f"-100{source_chat_id}")
            elif chat_type == "chat":
                chat_identifier = -source_chat_id
            else:
                # Unrecognized/legacy chat_type (e.g. a pre-repair "unknown"
                # row): a bare source_chat_id would be misread by Telethon
                # as a PeerUser and is guaranteed to fail, wasting a
                # request. Bail out instead of guessing an identifier.
                self.logger.warning(
                    "Unrecognized chat_type '%s' for source %s, skipping user %s",
                    chat_type, source_chat_id, user_id,
                )
                return None
        chat_title = source_data.get("chat_title", str(source_chat_id))

        chat_entity, verdict = await self._resolve_chat_for_session(
            session_client, session_id, chat_identifier, source_chat_id
        )
        if verdict is True:
            # record even when chat_entity is None (member, but the resolve
            # itself was flaky) so the session stays selectable for this chat
            await self._update_access(source_chat_id, session_id, True)
        if chat_entity is None:
            if verdict is False:
                # Telegram says this session genuinely has no access. Try an
                # invite join if we have a hash, otherwise record the denial
                # and notify.
                chat_entity = await self._try_join_private_group(
                    session_client, session_id, source_chat_id,
                    source_data.get("invite_hash"), chat_title, chat_identifier,
                )
                if chat_entity is None:
                    return None
            else:
                # verdict None (couldn't tell) or True-without-entity: skip
                # this one user, but never bench the session over it.
                return None

        user_entity = None

        if source_data["chat_type"] == "broadcast" and source_post_id is not None:
            try:
                async for comment in session_client.iter_messages(
                    chat_entity, reply_to=source_post_id
                ):
                    sender = await comment.get_sender()  # InputPeerUser
                    if isinstance(sender, User) and sender.id == user_id:
                        user_entity = sender
                        break
            except MsgIdInvalidError:
                self.logger.warning(
                    (
                        f"Post with id '{source_post_id} could be deleted."
                        f"Skipping post from channel '{chat_entity.title}'..."
                    )
                )
            except Exception as e:
                self.logger.error(
                    f"Unexpected error occurred. Skip channel {source_data['chat_username']}: {e}",
                    exc_info=True,
                )
                return None
        elif source_data["chat_type"] in ("megagroup", "gigagroup", "chat"):
            try:
                if source_post_id is not None:
                    message = await session_client.get_messages(
                        chat_entity, ids=source_post_id
                    )
                    if message is not None:
                        sender = await message.get_sender()
                        if isinstance(sender, User) and sender.id == user_id:
                            user_entity = sender
                else:
                    participants = await self._get_group_participants(
                        session_client, session_id, chat_entity, source_chat_id
                    )
                    user_entity = participants.get(user_id)
            except MsgIdInvalidError:
                self.logger.warning(
                    (
                        f"Message with id '{source_post_id} could be deleted."
                        f"Skipping message from group '{chat_entity.title}'..."
                    )
                )
            except ChannelPrivateError as e:
                self.logger.error(
                    f"Channel privacy corrupted. Skip group {source_data['chat_username']}: {e}",
                    exc_info=True,
                )
                return None
            except Exception as e:
                self.logger.error(
                    f"Unexpected error occurred. Skip group {source_data['chat_username']}: {e}",
                    exc_info=True,
                )
                return None

        if user_entity:
            if getattr(user_entity, "min", False) and getattr(user_entity, "username", None):
                # A `min` participant's access hash only works inside the
                # source channel; resolve the username to a full entity so
                # the DM is not rejected with PeerIdInvalidError.
                try:
                    full = await session_client.get_entity(user_entity.username)
                    return await session_client.get_input_entity(full)
                except Exception:
                    pass
            try:
                return await session_client.get_input_entity(user_entity)
            except ValueError:
                pass

        return None

    def _get_session_file(self, session_id: int) -> str:
        for si in self.session_wrappers:
            if si.session_id == session_id:
                return si.wrapper.session_file
        return str(session_id)

    async def _session_dialog_ids(self, session_client, session_id):
        """Entity ids of every dialog the session has open, scanned once
        per run (returns None if the scan itself failed). A get_entity() by
        bare -100{id} fails for a channel that is not in the session's
        local entity cache even when the account is a member; the dialog
        list is the reliable membership signal and the scan also warms the
        cache so the next get_entity() succeeds."""
        sid = int(session_id)
        if sid not in self._dialog_ids_cache:
            try:
                ids: set[int] = set()
                async for dialog in session_client.iter_dialogs():
                    entity = dialog.entity
                    if entity is not None:
                        ids.add(entity.id)
                self._dialog_ids_cache[sid] = ids
            except Exception:
                self.logger.warning(
                    "Dialog scan failed for session %s", session_id, exc_info=True
                )
                self._dialog_ids_cache[sid] = None
        return self._dialog_ids_cache[sid]

    async def _resolve_chat_for_session(
        self, session_client, session_id, chat_identifier, raw_chat_id
    ):
        """Resolve a source chat for one session.

        Returns (entity_or_None, verdict) where verdict is:
          True  - the session can reach the chat
          False - Telegram says it cannot (ChannelPrivateError)
          None  - undetermined (bare id not cached, transient error). A
                  None verdict must never be persisted as a denial, or a
                  temporary miss benches the session for good.
        """
        try:
            return await session_client.get_entity(chat_identifier), True
        except ChannelPrivateError:
            return None, False
        except (ValueError, TypeError):
            pass
        except UsernameNotOccupiedError:
            self.logger.warning("Chat %s no longer exists", chat_identifier)
            return None, False
        except Exception:
            self.logger.warning(
                "Access probe error for chat %s on session %s",
                raw_chat_id, session_id, exc_info=True,
            )
            return None, None

        # Bare id wasn't in this session's cache. A member still has the
        # chat in their dialog list - scan once, then retry the resolve.
        dialog_ids = await self._session_dialog_ids(session_client, session_id)
        if dialog_ids is None:
            return None, None  # scan failed - can't tell, don't persist
        if raw_chat_id in dialog_ids:
            try:
                return await session_client.get_entity(chat_identifier), True
            except Exception:
                return None, True
        return None, False  # not in the dialog list => genuinely not a member

    async def _mark_group_inaccessible(
        self, session_id: int, chat_id: int, chat_title: str, chat_identifier
    ):
        accessible = []
        sm = self.main_window.session_manager
        if sm:
            # Probe every live session so one notification pass also
            # refreshes the access table for the rest. Only a definite
            # verdict (see _resolve_chat_for_session) is persisted - an
            # "undetermined" session is left untouched so it is retried on
            # the next run instead of being permanently benched.
            for sf, wrapper in sm.sessions.items():
                _, verdict = await self._resolve_chat_for_session(
                    wrapper.client, wrapper.session_id, chat_identifier, chat_id
                )
                if verdict is True:
                    accessible.append(sf)
                    await self._update_access(chat_id, wrapper.session_id, True)
                elif verdict is False:
                    await self._update_access(chat_id, wrapper.session_id, False)
        session_file = self._get_session_file(session_id)
        accessible_str = ", ".join(accessible) if accessible else "нет доступных сессий"
        self.main_window.show_notification(
            "Нет доступа к группе",
            f"Сессия '{session_file}' не может получить доступ к группе '{chat_title}'.\n"
            f"Пользователи из этой группы будут пропущены для данной сессии.\n"
            f"Сессии с доступом: {accessible_str}",
        )

    async def _try_join_private_group(
        self, session_client, session_id: int, chat_id: int,
        invite_hash: str | None, chat_title: str, chat_identifier,
    ):
        if invite_hash:
            try:
                result = await session_client(CheckChatInviteRequest(invite_hash))
                if isinstance(result, ChatInviteAlready):
                    return result.chat
                join_result = await session_client(ImportChatInviteRequest(invite_hash))
                if join_result.chats:
                    return join_result.chats[0]
            except Exception as e:
                self.logger.error(f"Cannot join group {chat_id} via hash: {e}", exc_info=True)
        await self._mark_group_inaccessible(session_id, chat_id, chat_title, chat_identifier)
        return None

    def _note_unreached(self, chat_id) -> None:
        if chat_id is None:
            return
        self._unreached_chats[chat_id] = self._unreached_chats.get(chat_id, 0) + 1

    @staticmethod
    def _format_group_label(chat_id: int, source: dict) -> str:
        title = source.get("chat_title") or "без названия"
        parts = [f"id {chat_id}"]
        username = source.get("chat_username")
        if username:
            parts.append(f"@{username}")
        invite_hash = source.get("invite_hash")
        if invite_hash:
            parts.append(f"https://t.me/+{invite_hash}")
        return f"«{title}» ({', '.join(parts)})"

    async def _report_unreached_groups(self) -> None:
        if not self._unreached_chats and not self._undeliverable:
            return

        message_parts = []
        if self._undeliverable:
            message_parts.append(
                f"{self._undeliverable} пользовател(ей) удалось найти, но отправить "
                f"им нельзя — закрытые настройки приватности, аккаунт удалён, либо "
                f"пользователь получен из участников группы и ему нельзя написать "
                f"первым (нет username)."
            )

        chat_ids = list(self._unreached_chats.keys())
        access_by_chat = await self.main_window.database.get_chat_access_sessions(chat_ids)

        with_access_lines = []
        without_access_lines = []
        for chat_id in chat_ids:
            source = await self.main_window.database.get_parse_source(chat_id)
            label = self._format_group_label(chat_id, source)
            sessions = access_by_chat.get(chat_id)
            if sessions:
                session_parts = ", ".join(
                    f"{s['session_id']} {s['session_file']} ({s['phone_number'] or 'без номера'})"
                    for s in sessions
                )
                with_access_lines.append(f"{label} — {session_parts}")
            else:
                without_access_lines.append(label)

        if with_access_lines:
            message_parts.append(
                "Часть пользователей не была разослана — доступ к их группам есть "
                "у сессий, не выбранных для этой рассылки:\n" + "\n".join(with_access_lines)
            )
        if without_access_lines:
            message_parts.append(
                "Группы без доступных сессий (нужно найти/подключить сессию с "
                "доступом к ним):\n" + "\n".join(without_access_lines)
            )

        self.logger.warning(
            "Mailing finished: unreached from %d group(s): %s; undeliverable: %d",
            len(chat_ids), self._unreached_chats, self._undeliverable,
        )
        if message_parts:
            self.main_window.show_notification(
                "Не все пользователи получили сообщение",
                "\n\n".join(message_parts),
            )

    async def stop(self):
        if not self._running:
            return
        self.logger.info("Stopping mailing")
        await self._report_unreached_groups()
        self._running = False
        if self.update_task:
            self.update_task.cancel()
            try:
                await self.update_task
            except asyncio.CancelledError:
                pass
        self.update_task = None
        self.main_window.settings_bridge.finishMailing.emit()

    async def start_sessions(self):
        session_manager = self.main_window.session_manager
        if session_manager is None:
            return
        for session_id, session_file in self.session_files.items():
            session_wrapper = session_manager.get_wrapper(session_file)
            was_started = False
            if not session_wrapper:
                session_wrapper = await session_manager.start_session(
                    session_id, session_file, is_module=True
                )
                was_started = True
            if session_wrapper is None:
                self.logger.warning(
                    f"Session {session_file} failed to start, skipping"
                )
                continue
            self.session_wrappers.append(
                self.SessionWrapperInfo(session_wrapper, was_started, session_id, 0)
            )

    async def _check_spambot_status(self, wrapper) -> None:
        if not self.main_window.settings_manager.get_setting("auto_write_spambot"):
            return
        try:
            result = await wrapper.check_spam_status()
            title, message = format_spam_status_notification(wrapper.session_file, result)
            self.main_window.show_notification(title, message)
            self.logger.info(f"{wrapper.session_file}\tSpamBot check: {result}")
        except Exception as e:
            self.logger.error(
                f"{wrapper.session_file}\tSpamBot check failed", exc_info=e
            )

    async def finish_session(self, session_id):
        session = next(
            (s for s in self.session_wrappers if s.session_id == session_id), None
        )
        if session and session.was_started:
            await self.main_window.session_manager.stop_session(
                session.wrapper.session_file
            )
        self.session_wrappers = [
            s for s in self.session_wrappers if s.session_id != session_id
        ]
        self.sessions_count = len(self.session_wrappers)

    async def sendUpdate(self):
        while self._running:
            total_processed_users = sum([s.sent_count for s in self.session_wrappers])
            total_seconds = (datetime.now() - self.start_time).total_seconds()
            common_time = total_seconds * (
                self.total_users_count / (total_processed_users + 0.001)
            )
            H1 = int(total_seconds // 3600)
            M1 = int((total_seconds // 60) % 60)
            S1 = int(total_seconds % 60)
            H2 = int(common_time // 3600)
            M2 = int((common_time // 60) % 60)
            S2 = int(common_time % 60)
            time = f"{H1:02}:{M1:02}:{S1:02}/{H2:02}:{M2:02}:{S2:02}"

            self.main_window.settings_bridge.renderMailingProgressData.emit(
                json.dumps(
                    {
                        "status": "рассылка",
                        "total_count": f"{total_processed_users}/{self.total_users_count}",
                        "time": time,
                    }
                )
            )

            await asyncio.sleep(UPDATE_DELAY)

    @property
    def running(self):
        return self._running
