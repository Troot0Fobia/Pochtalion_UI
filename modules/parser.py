import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon.tl import types
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
from telethon.tl.types import (
    Channel,
    ChannelParticipantAdmin,
    ChannelParticipantCreator,
    ChatInviteAlready,
    UserStatusEmpty,
    UserStatusLastMonth,
    UserStatusLastWeek,
    UserStatusOffline,
    UserStatusOnline,
    UserStatusRecently,
)

from core.logger import setup_logger

PARSE_DELAY = 1
UPDATE_DELAY = 1


class Parser:

    def __init__(self, main_window):
        self.main_window = main_window
        self.is_parse_channel = None
        self.count_of_posts = None
        self.is_parse_messages = None
        self.count_of_messages = None
        self.session_files = None
        self._running = False
        self._session_user_ids: set[int] = set()
        self.update_task = None
        self.logger = setup_logger("Pochtalion.Parser", "parser.log")

    async def start(self, parser_data_str):
        self.logger.info("Start parsing")
        parser_data = json.loads(parser_data_str)
        self.count_of_posts = parser_data["count_of_posts"].strip()
        self.is_parse_messages = parser_data["is_parse_messages"]
        self.count_of_messages = parser_data["count_of_messages"].strip()
        self.session_files = parser_data["selected_sessions"]
        self.saved_to_db = self.parse_to_db = (
            self.main_window.settings_manager.get_setting("force_parse_to_db")
        )
        self.parse_targets = []  # list of {"kind": "public", "value": str} | {"kind": "private", "hash": str}
        self.existing_ids = {}
        self.group_data = {}
        self._sent_user_ids: set[int] = set()
        is_parse_admins = self.main_window.settings_manager.get_setting("parse_admins")
        self.send_links_to_parsed = self.main_window.settings_manager.get_setting("send_links_to_parsed")
        self.send_links_type = self.main_window.settings_manager.get_setting("send_links_type") or "messages_and_username"
        self.last_seen_filter = self.main_window.settings_manager.get_setting("parse_last_seen_filter") or "any"

        public_pattern = re.compile(
            r"""
            (
                ((?P<url>^https?:\/\/t\.me\/(?P<group_username>[a-zA-Z0-9_]{5,32}))($|\/(?P<post_id>\d+))
                |^@(?P<username>[a-z0-9_]{5,32}$))
            )
        """,
            re.VERBOSE,
        )
        invite_pattern = re.compile(
            r"^https?://t\.me/(?:joinchat/|\+)([a-zA-Z0-9_=-]+)$"
        )
        addlist_pattern = re.compile(
            r"^(?:https?://)?t\.me/addlist/([a-zA-Z0-9_-]+)$"
        )
        self._folder_links: list[str] = []

        for link in parser_data["parse_links"].splitlines():
            link = link.strip()
            if re.match(addlist_pattern, link):
                self._folder_links.append(link)
                continue
            invite_matched = re.match(invite_pattern, link)
            if invite_matched:
                self.parse_targets.append({"kind": "private", "hash": invite_matched.group(1)})
                continue
            public_matched = re.match(public_pattern, link)
            if public_matched:
                self.parse_targets.append({
                    "kind": "public",
                    "value": public_matched.group("group_username") or public_matched.group("username"),
                })

        session_groups = parser_data.get("session_groups", {})
        for session_id_str, identifiers in session_groups.items():
            for identifier in identifiers:
                identifier = identifier.strip()
                if not identifier:
                    continue
                if identifier.startswith("@"):
                    self.parse_targets.append({
                        "kind": "public",
                        "value": identifier[1:].lower(),
                        "session_id": session_id_str,
                    })
                elif identifier.startswith("-") and identifier[1:].isdigit():
                    self.parse_targets.append({
                        "kind": "numeric",
                        "value": int(identifier),
                        "session_id": session_id_str,
                    })

        if (
            not self.parse_targets and not self._folder_links
            or not self.session_files
            or self.is_parse_messages
            and not self.count_of_messages.isdigit()
        ):
            self.logger.warning("Incorrect data provided. Returning...")
            self.main_window.show_notification("Внимание", "Некорректные данные")
            return

        self.count_of_messages = int(self.count_of_messages or 0)
        self.count_of_posts = int(self.count_of_posts or 0)
        self.logger.info(
            "Parse config: targets=%d, folder_links=%d, sessions=%d | "
            "parse_to_db=%s, send_links=%s, send_links_type=%s | "
            "by_messages=%s, count_posts=%d, count_msgs=%d | "
            "last_seen=%s, parse_admins=%s",
            len(self.parse_targets),
            len(self._folder_links),
            len(self.session_files),
            self.parse_to_db,
            self.send_links_to_parsed,
            self.send_links_type,
            self.is_parse_messages,
            self.count_of_posts,
            self.count_of_messages,
            self.last_seen_filter,
            is_parse_admins,
        )
        self._running = True
        self.session_wrappers = []
        self.group_id = None
        await self.start_sessions()
        await self._expand_folder_links()

        self._session_user_ids = {
            wrapper.session_user_id
            for wrapper, _, _ in self.session_wrappers
            if getattr(wrapper, "session_user_id", None) is not None
        }

        sessions_count = len(self.session_wrappers)
        index = 0
        self.start_time = datetime.now()
        self.update_task = asyncio.create_task(self.sendUpdate())

        while self.parse_targets:
            if not self._running:
                break

            target = self.parse_targets.pop()
            if "session_id" in target:
                constraint = str(target["session_id"])
                matched = next(
                    (w for w, _, sid in self.session_wrappers if str(sid) == constraint),
                    None,
                )
                if matched is None:
                    self.logger.warning(f"Session {constraint} not found, skipping {target}")
                    continue
                wrapper = matched
                session_id = constraint
            else:
                wrapper, _, session_id = self.session_wrappers[index % sessions_count]
                index += 1
            client = wrapper.client

            try:
                if target["kind"] == "private":
                    group_entity = await self._join_private_group(client, target["hash"])
                    parse_username = f"private:{target['hash'][:8]}"
                elif target["kind"] == "numeric":
                    group_entity = await client.get_entity(target["value"])
                    parse_username = str(target["value"])
                else:
                    parse_username = target["value"]
                    group_entity = await client.get_entity(parse_username)
            except Exception:
                self.logger.error(
                    f"Failed to get entity for {target}, skipping",
                    exc_info=True,
                )
                continue
            group_type = self._get_channel_type(group_entity)
            self.group_id = group_entity.id
            self.group_data[self.group_id] = (
                group_entity.title,
                getattr(group_entity, "username", None),
                group_type,
                target.get("hash"),  # invite_hash; None for public/numeric targets
            )
            await self.main_window.database.add_parse_source(
                self.group_id, *self.group_data[self.group_id]
            )

            if group_type == "broadcast":
                _strategy = "broadcast→comments"
            elif self.is_parse_messages:
                _strategy = f"messages (limit={self.count_of_messages or 'all'})"
            else:
                _strategy = "participants"
            self.logger.info(
                "Parsing '%s' (@%s, %s) via session %s | strategy: %s",
                group_entity.title,
                getattr(group_entity, "username", None) or "no_username",
                group_type,
                wrapper.session_file,
                _strategy,
            )

            if group_type == "broadcast":
                try:
                    async for message in client.iter_messages(
                        group_entity, self.count_of_posts or None
                    ):
                        if not message.post:
                            continue
                        try:
                            async for comment in client.iter_messages(
                                group_entity, reply_to=message.id
                            ):
                                user_entity = await comment.get_sender()
                                if not self._check_user_needness(
                                    user_entity, is_parse_admins
                                ):
                                    continue
                                await client.get_input_entity(user_entity)
                                is_new = await self._handle_user(
                                    user_entity, message.id, session_id, wrapper
                                )
                                if self.send_links_to_parsed:
                                    link_sent = await self._send_link_to_saved(
                                        user_entity, group_entity, client, comment.id
                                    )
                                    if not link_sent and is_new and self.parse_to_db:
                                        ud = dict(self.existing_ids[user_entity.id][3])
                                        ud["user_id"] = user_entity.id
                                        await wrapper.process_new_user(
                                            ud, last_message=None, user_status=4,
                                            sended=False, source_chat_id=self.group_id,
                                            source_post_id=message.id,
                                        )
                                await asyncio.sleep(PARSE_DELAY)
                        except Exception:
                            # this throw unknown shit like
                            # telethon.errors.rpcerrorlist.MsgIdInvalidError: \
                            # The message ID used in the peer was invalid (caused by GetRepliesRequest)
                            # but message matches for channel's post
                            # https://github.com/LonamiWebs/Telethon/issues/3841
                            # https://github.com/LonamiWebs/Telethon/issues/3837
                            # https://stackoverflow.com/questions/72396273/how-to-use-getrepliesrequest-call-in-telethon
                            pass
                        await asyncio.sleep(PARSE_DELAY)
                except Exception:
                    self.logger.error(
                        "Unexpected error while parsing broadcast '%s' (@%s)",
                        group_entity.title,
                        getattr(group_entity, "username", None) or "no_username",
                        exc_info=True,
                    )
            elif group_type in ("megagroup", "gigagroup", "chat"):
                if self.is_parse_messages:
                    async for message in client.iter_messages(
                        group_entity, self.count_of_messages or None
                    ):
                        try:
                            user_entity = await message.get_sender()
                            if user_entity is None and message.sender_id is not None:
                                try:
                                    user_entity = await client.get_entity(message.sender_id)
                                except Exception:
                                    pass
                            if not self._check_user_needness(
                                user_entity, is_parse_admins
                            ):
                                continue
                            await client.get_input_entity(user_entity)
                            is_new = await self._handle_user(
                                user_entity, message.id, session_id, wrapper
                            )
                            if self.send_links_to_parsed:
                                link_sent = await self._send_link_to_saved(
                                    user_entity, group_entity, client, message.id
                                )
                                if not link_sent and is_new and self.parse_to_db:
                                    ud = dict(self.existing_ids[user_entity.id][3])
                                    ud["user_id"] = user_entity.id
                                    await wrapper.process_new_user(
                                        ud, last_message=None, user_status=4,
                                        sended=False, source_chat_id=self.group_id,
                                        source_post_id=message.id,
                                    )
                            await asyncio.sleep(PARSE_DELAY)
                        except Exception:
                            self.logger.error(
                                "Unexpected error while parsing '%s' (@%s) by messages, msg_id=%s",
                                group_entity.title,
                                getattr(group_entity, "username", None) or "no_username",
                                getattr(message, "id", "?"),
                                exc_info=True,
                            )
                else:
                    async for user_entity in client.iter_participants(group_entity):
                        try:
                            if not self._check_user_needness(
                                user_entity, is_parse_admins
                            ):
                                continue
                            await client.get_input_entity(user_entity)
                            is_new = await self._handle_user(
                                user_entity, None, session_id, wrapper
                            )
                            if self.send_links_to_parsed:
                                link_sent = await self._send_link_to_saved(
                                    user_entity, group_entity, client
                                )
                                if not link_sent and is_new and self.parse_to_db:
                                    ud = dict(self.existing_ids[user_entity.id][3])
                                    ud["user_id"] = user_entity.id
                                    await wrapper.process_new_user(
                                        ud, last_message=None, user_status=4,
                                        sended=False, source_chat_id=self.group_id,
                                        source_post_id=None,
                                    )
                            await asyncio.sleep(PARSE_DELAY)
                        except Exception:
                            self.logger.error(
                                "Unexpected error while parsing '%s' (@%s) by participants, user_id=%s",
                                group_entity.title,
                                getattr(group_entity, "username", None) or "no_username",
                                getattr(user_entity, "id", "?"),
                                exc_info=True,
                            )
            else:
                self.logger.warning(
                    f"Unsupported entity type '{group_type}' for {parse_username}, skipping"
                )

        await self.stop()

    def _check_user_needness(self, user_entity, is_parse_admins) -> bool:
        if user_entity is None:
            return False

        if isinstance(user_entity, Channel):
            return False

        if user_entity.bot:
            return False

        if user_entity.id in self._session_user_ids:
            return False

        if is_parse_admins:
            return True

        if isinstance(user_entity, ChannelParticipantAdmin) or isinstance(
            user_entity, ChannelParticipantCreator
        ):
            return False

        if not self._passes_last_seen_filter(user_entity):
            return False

        return True

    def _passes_last_seen_filter(self, user_entity) -> bool:
        if self.last_seen_filter == "any":
            return True
        status = getattr(user_entity, "status", None)
        if status is None or isinstance(status, UserStatusEmpty):
            return False
        if isinstance(status, (UserStatusOnline, UserStatusRecently, UserStatusLastWeek)):
            return True
        if isinstance(status, UserStatusLastMonth):
            return self.last_seen_filter == "this_month"
        if isinstance(status, UserStatusOffline):
            was_online = getattr(status, "was_online", None)
            if was_online is None:
                return False
            delta = datetime.now(timezone.utc) - was_online
            if self.last_seen_filter == "this_week":
                return delta.days <= 7
            if self.last_seen_filter == "this_month":
                return delta.days <= 30
        return False

    async def _handle_user(self, user_entity, message_id, session_id, wrapper) -> bool:
        if (
            isinstance(user_entity, types.User)
            and not user_entity.bot
            and not user_entity.deleted
        ):
            if user_entity.id not in self.existing_ids.keys():
                user_data = {
                    "first_name": getattr(user_entity, "first_name", None),
                    "last_name": getattr(user_entity, "last_name", None),
                    "username": getattr(user_entity, "username", None),
                    "phone_number": getattr(user_entity, "phone", None),
                }
                self.existing_ids[user_entity.id] = (
                    self.group_id,
                    message_id,
                    session_id,
                    user_data,
                )
                if self.parse_to_db and not self.send_links_to_parsed:
                    user_data["user_id"] = user_entity.id
                    await wrapper.process_new_user(
                        user_data,
                        last_message=None,
                        user_status=4,
                        sended=False,
                        source_chat_id=self.group_id,
                        source_post_id=message_id,
                    )
                return True
        return False

    async def _send_link_to_saved(self, user_entity, group_entity, client, message_id=None) -> bool:
        if user_entity.id in self._sent_user_ids:
            return True

        mode = self.send_links_type
        group_username = getattr(group_entity, "username", None)

        if mode == "username":
            username = getattr(user_entity, "username", None)
            if not username:
                return False
            link = f"@{username}"
        elif mode == "usernames_and_messages":
            username = getattr(user_entity, "username", None)
            if username:
                link = f"@{username}"
            else:
                link = None
                if message_id is not None:
                    link = (
                        f"https://t.me/{group_username}/{message_id}"
                        if group_username
                        else f"https://t.me/c/{group_entity.id}/{message_id}"
                    )
                else:
                    try:
                        async for msg in client.iter_messages(
                            group_entity, from_user=user_entity, limit=1
                        ):
                            link = (
                                f"https://t.me/{group_username}/{msg.id}"
                                if group_username
                                else f"https://t.me/c/{group_entity.id}/{msg.id}"
                            )
                            break
                    except Exception:
                        self.logger.warning(
                            f"Could not fetch messages for user {user_entity.id}", exc_info=True
                        )
                if link is None:
                    return False
        else:
            # "messages" or "messages_and_username"
            link = None
            if message_id is not None:
                link = (
                    f"https://t.me/{group_username}/{message_id}"
                    if group_username
                    else f"https://t.me/c/{group_entity.id}/{message_id}"
                )
            else:
                try:
                    async for msg in client.iter_messages(
                        group_entity, from_user=user_entity, limit=1
                    ):
                        link = (
                            f"https://t.me/{group_username}/{msg.id}"
                            if group_username
                            else f"https://t.me/c/{group_entity.id}/{msg.id}"
                        )
                        break
                except Exception:
                    self.logger.warning(
                        f"Could not fetch messages for user {user_entity.id}", exc_info=True
                    )

            if link is None and mode == "messages_and_username":
                username = getattr(user_entity, "username", None)
                if username:
                    link = f"@{username}"

            if link is None:
                return False

        try:
            await client.send_message("me", link)
            self._sent_user_ids.add(user_entity.id)
            return True
        except Exception:
            self.logger.error(
                f"Failed to send to saved messages for user {user_entity.id}",
                exc_info=True,
            )
            return False

    async def _expand_folder_links(self) -> None:
        if not self._folder_links or not self.session_wrappers:
            return

        first_wrapper = self.session_wrappers[0][0]
        new_targets: list[dict] = []

        for link in self._folder_links:
            identifiers = await first_wrapper.resolve_chat_folder(link)
            if not identifiers:
                self.logger.warning(f"Folder link {link} resolved to 0 groups, skipping")
                continue

            # All other sessions also join the groups from the folder
            for wrapper, _, _ in self.session_wrappers[1:]:
                await wrapper.resolve_chat_folder(link)

            for identifier in identifiers:
                if identifier.startswith("@"):
                    new_targets.append({"kind": "public", "value": identifier.lstrip("@")})
                else:
                    # Private group: already joined, use numeric ID for get_entity()
                    new_targets.append({"kind": "numeric", "value": int(identifier)})

        self.parse_targets.extend(new_targets)
        self.logger.info(
            f"Expanded {len(self._folder_links)} folder link(s) → {len(new_targets)} additional targets"
        )

    async def _join_private_group(self, client, invite_hash):
        result = await client(CheckChatInviteRequest(invite_hash))
        if isinstance(result, ChatInviteAlready):
            return result.chat
        join_result = await client(ImportChatInviteRequest(invite_hash))
        if join_result.chats:
            return join_result.chats[0]
        raise RuntimeError(f"No chat entity returned after joining with hash {invite_hash[:8]}")

    async def start_sessions(self):
        session_manager = self.main_window.session_manager
        if session_manager is None or self.session_files is None:
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
            self.session_wrappers.append((session_wrapper, was_started, session_id))

    # async def finish_sessions(self):
    #     for session_wrapper, was_started, _ in self.session_wrappers:
    #         if was_started:
    #             await self.main_window.session_manager.stop_session(session_wrapper.session_file)
    #     self.session_wrappers = []

    async def export_csv(self):
        import csv

        from PyQt6.QtWidgets import QFileDialog

        self.logger.info("Export result of parsing to csv file")

        filepath, _ = QFileDialog.getSaveFileName(
            self.main_window,
            "Сохранить CSV",
            "parsed_users.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if filepath:
            with open(Path(filepath), mode="w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "user_id",
                        "username",
                        "first_name",
                        "last_name",
                        "phone_number",
                        "source_chat_id",
                        "chat_title",
                        "chat_username",
                        "chat_type",
                        "post_id",
                    ],
                )
                writer.writeheader()
                for user_id, (
                    group_id,
                    post_id,
                    _,
                    user_data,
                ) in self.existing_ids.items():
                    group_title, group_username, group_type, *_ = self.group_data[group_id]
                    writer.writerow(
                        {
                            "user_id": user_id,
                            "username": user_data.get("username", None),
                            "first_name": user_data.get("first_name", None),
                            "last_name": user_data.get("last_name", None),
                            "phone_number": user_data.get("phone_number", None),
                            "source_chat_id": group_id,
                            "chat_title": group_title,
                            "chat_username": group_username,
                            "chat_type": group_type,
                            "post_id": post_id,
                        }
                    )
        else:
            self.main_window.show_notification("Отменено", "Сохранение отменено")

    async def save_to_db(self):
        if self.saved_to_db:
            self.main_window.show_notification(
                "Внимание", "Данные уже добавлены в базу данных"
            )
            return

        self.logger.info("Save results of parsing to database")
        await self.start_sessions()
        last_session_id = None
        s_wrapper = None
        self.start_time = datetime.now()
        self.saving = True
        self.saved_count = 0
        self.update_task = asyncio.create_task(self.sendUpdateSaveToDB())
        for user_id, (
            group_id,
            post_id,
            session_id,
            user_data,
        ) in self.existing_ids.items():
            if last_session_id != session_id:
                s_wrapper = next(
                    (
                        wrapper
                        for wrapper, _, sid in self.session_wrappers
                        if sid == session_id
                    ),
                    None,
                )
                last_session_id = session_id
            user_data["user_id"] = user_id
            if s_wrapper:
                await s_wrapper.process_new_user(
                    user_data,
                    last_message=None,
                    user_status=4,
                    sended=False,
                    source_chat_id=group_id,
                    source_post_id=post_id,
                )
                self.saved_count += 1
        self.saved_to_db = True
        self.saving = False
        if self.update_task:
            self.update_task.cancel()
            try:
                await self.update_task
            except asyncio.CancelledError:
                pass
        self.update_task = None
        self.main_window.settings_bridge.finishParsing.emit()
        # await self.finish_sessions()

    def _get_channel_type(self, entity) -> str:
        if isinstance(entity, types.Channel):
            if entity.broadcast:
                return "broadcast"
            if entity.megagroup:
                return "megagroup"
            if entity.gigagroup:
                return "gigagroup"
        elif isinstance(entity, types.Chat):
            return "chat"
        else:
            return "unknown"
        return "unknown"

    async def stop(self):
        if not self._running or not self.session_wrappers:
            return
        self.logger.info("Stop parsing")
        self._running = False
        self.saving = False
        self.is_parse_channel = None
        self.count_of_posts = None
        self.is_parse_messages = None
        self.count_of_messages = None
        self.parse_targets = []

        if self.update_task:
            self.update_task.cancel()
            try:
                await self.update_task
            except asyncio.CancelledError:
                pass
        self.update_task = None
        self.main_window.settings_bridge.finishParsing.emit()
        self.session_wrappers = []
        # await self.finish_sessions()

    async def sendUpdate(self):
        _consecutive_errors = 0
        while self._running:
            try:
                group_title, group_username, group_type, *_ = self.group_data.get(
                    self.group_id, ("Unknown", "Unknown", "Unknown", None)
                )
                total_seconds = (datetime.now() - self.start_time).total_seconds()
                H = int(total_seconds // 3600)
                M = int((total_seconds // 60) % 60)
                S = int(total_seconds % 60)
                elapsed_time = f"{H:02}:{M:02}:{S:02}"

                self.main_window.settings_bridge.renderParsingProgressData.emit(
                    json.dumps(
                        {
                            "status": "парсинг",
                            "total_count": len(self.existing_ids),
                            "chat": f"{group_title} @{group_username} {group_type}",
                            "elapsed_time": elapsed_time,
                        }
                    )
                )
                _consecutive_errors = 0
            except Exception:
                _consecutive_errors += 1
                self.logger.error(
                    "sendUpdate error (consecutive: %d)", _consecutive_errors, exc_info=True
                )
                if _consecutive_errors >= 5:
                    self.logger.error("sendUpdate failed 5 times in a row, stopping parser")
                    self._running = False
                    self.main_window.settings_bridge.finishParsing.emit()
                    return

            await asyncio.sleep(UPDATE_DELAY)

    async def sendUpdateSaveToDB(self):
        parsed_count = len(self.existing_ids)
        _consecutive_errors = 0
        while self.saving:
            try:
                group_title, group_username, group_type, *_ = self.group_data.get(
                    self.group_id, ("Unknown", "Unknown", "Unknown", None)
                )
                total_seconds = (datetime.now() - self.start_time).total_seconds()
                H = int(total_seconds // 3600)
                M = int((total_seconds // 60) % 60)
                S = int(total_seconds % 60)
                elapsed_time = f"{H:02}:{M:02}:{S:02}"

                self.main_window.settings_bridge.renderParsingProgressData.emit(
                    json.dumps(
                        {
                            "status": "сохранение",
                            "total_count": f"{self.saved_count}/{parsed_count}",
                            "chat": f"{group_title} @{group_username} {group_type}",
                            "elapsed_time": elapsed_time,
                        }
                    )
                )
                _consecutive_errors = 0
            except Exception:
                _consecutive_errors += 1
                self.logger.error(
                    "sendUpdateSaveToDB error (consecutive: %d)", _consecutive_errors, exc_info=True
                )
                if _consecutive_errors >= 5:
                    self.logger.error("sendUpdateSaveToDB failed 5 times in a row, stopping parser")
                    self.saving = False
                    self.main_window.settings_bridge.finishParsing.emit()
                    return

            await asyncio.sleep(UPDATE_DELAY)

    @property
    def running(self):
        return self._running
