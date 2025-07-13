import json
import re
import asyncio
from pathlib import Path
from telethon.tl import types
from datetime import datetime
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
        self.update_task = None
        self.logger = setup_logger("Pochtalion.Parser", "parser.log")


    async def start(self, parser_data_str):
        self.logger.info("Start parsing")
        self.logger.debug(f"Start parsing for data: {parser_data_str}")
        parser_data = json.loads(parser_data_str)
        self.is_parse_channel = parser_data['is_parse_channel']
        self.count_of_posts = parser_data['count_of_posts'].strip()
        self.is_parse_messages = parser_data['is_parse_messages']
        self.count_of_messages = parser_data['count_of_messages'].strip()
        self.session_files = parser_data['selected_sessions']
        self.saved_to_db = self.parse_to_db = self.main_window.settings_manager.get_setting('force_parse_to_db')
        self.parse_usernames = []
        self.existing_ids = {}
        self.group_data = {}

        for link in parser_data['parse_links'].splitlines():
            matched = re.match(r'((?P<url>^https?:\/\/t\.me\/(?P<group_username>[a-zA-Z0-9_]{5,32}))($|\/(?P<post_id>\d+))|^@(?P<username>[a-z0-9_]{5,32}$))', link.strip())
            if matched:
                self.parse_usernames.append(matched.group('group_username') or matched.group('username'))

        self.logger.debug(f"Received links {self.parse_usernames}")
        if not self.parse_usernames or not self.session_files or \
                self.is_parse_channel and not self.count_of_posts.isdigit() or \
                not self.is_parse_channel and self.is_parse_messages and not self.count_of_messages.isdigit():
            self.logger.warning("Incorrect data provided. Returning...")
            self.main_window.show_notification("Внимание", "Некорректные данные")
            return

        self.logger.debug(f"All data correct. Starting...")
        self.count_of_messages = int(self.count_of_messages or 0)
        self.count_of_posts = int(self.count_of_posts or 0)
        self._running = True
        self.session_wrappers = []
        self.group_id = None
        await self.start_sessions()

        sessions_count = len(self.session_wrappers)
        self.logger.debug(f"Sessions started {sessions_count}")
        index = 0
        self.start_time = datetime.now()
        self.update_task = asyncio.create_task(self.sendUpdate())

        while self.parse_usernames:
            if not self._running:
                break

            parse_username = self.parse_usernames.pop()
            wrapper, _, session_id = self.session_wrappers[index % sessions_count]
            client = wrapper.client
            index += 1

            group_entity = await client.get_entity(parse_username)
            group_type = self._get_channel_type(group_entity)
            self.group_id = group_entity.id
            self.group_data[self.group_id] = (group_entity.title, group_entity.username, group_type)
            await self.main_window.database.add_parse_source(self.group_id, *self.group_data[self.group_id])

            if group_type == "broadcast" and self.is_parse_channel:
                async for message in client.iter_messages(group_entity, self.count_of_posts or None):
                    if not message.post:
                        continue
                    # self.logger.debug(f"Received channel post: {message}")
                    # self.logger.debug(f"Message id: {message.id}")
                    try:
                        async for comment in client.iter_messages(group_entity, reply_to=message.id):
                            user_entity = await comment.get_sender()
                            await client.get_input_entity(user_entity)
                            await self._handle_user(user_entity, message.id, session_id, wrapper)
                            await asyncio.sleep(PARSE_DELAY)
                    except:
                        # this throw unknown shit like
                        # telethon.errors.rpcerrorlist.MsgIdInvalidError: The message ID used in the peer was invalid (caused by GetRepliesRequest)
                        # but message matches for channel's post
                        # https://github.com/LonamiWebs/Telethon/issues/3841
                        # https://github.com/LonamiWebs/Telethon/issues/3837
                        # https://stackoverflow.com/questions/72396273/how-to-use-getrepliesrequest-call-in-telethon
                        pass
                    await asyncio.sleep(PARSE_DELAY)
            elif group_type in ("megagroup", "gigagroup", "chat") and not self.is_parse_channel:
                if self.is_parse_messages:
                    async for message in client.iter_messages(group_entity, self.count_of_messages or None):
                        user_entity = await message.get_sender()
                        await client.get_input_entity(user_entity)
                        await self._handle_user(user_entity, message.id, session_id, wrapper)
                        await asyncio.sleep(PARSE_DELAY)
                else:
                    async for user_entity in client.iter_participants(group_entity):
                        await client.get_input_entity(user_entity)
                        await self._handle_user(user_entity, None, session_id, wrapper)
                        await asyncio.sleep(PARSE_DELAY)

        await self.stop()


    async def _handle_user(self, user_entity, message_id, session_id, wrapper):
        if isinstance(user_entity, types.User) and not user_entity.bot and not user_entity.deleted:
            self.logger.debug(f"Received new user with id {user_entity.id}. Processing...")
            if not user_entity.id in self.existing_ids.keys():
                user_data = {
                    "first_name": getattr(user_entity, 'first_name', None),
                    "last_name": getattr(user_entity, 'last_name', None),
                    "username": getattr(user_entity, 'username', None),
                    "phone_number": getattr(user_entity, 'phone_number', None)
                }
                self.existing_ids[user_entity.id] = (
                    self.group_id,
                    message_id,
                    session_id,
                    user_data
                )
                if self.parse_to_db:
                    user_data['user_id'] = user_entity.id
                    await wrapper.process_new_user(
                        user_data,
                        last_message=None,
                        user_status=4,
                        sended=False,
                        source_chat_id=self.group_id,
                        source_post_id=message_id
                    )


    async def start_sessions(self):
        self.logger.debug(f"Starting sessions: {self.session_files}")
        for session_id, session_file in self.session_files.items():
            session_wrapper = self.main_window.session_manager.get_wrapper(session_file)
            was_started = False
            if not session_wrapper:
                self.logger.debug(f"Session {session_file} was not started. Starting...")
                session_wrapper = await self.main_window.session_manager.start_session(session_id, session_file, is_module=True)
                was_started = True
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
            "CSV Files (*.csv);;All Files (*)"
        )
        if filepath:
            with open(Path(filepath), mode="w", newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=[
                    "user_id", "username", "first_name", "last_name", "phone_number",
                    "source_chat_id", "chat_title", "chat_username", "chat_type", "post_id"
                ])
                writer.writeheader()
                for user_id, (group_id, post_id, _, user_data) in self.existing_ids.items():
                    group_title, group_username, group_type = self.group_data[group_id]
                    writer.writerow({
                        "user_id": user_id,
                        "username": user_data.get('username', None),
                        "first_name": user_data.get('first_name', None),
                        "last_name": user_data.get('last_name', None),
                        "phone_number": user_data.get('phone_number', None),
                        "source_chat_id": group_id,
                        "chat_title": group_title,
                        "chat_username": group_username,
                        "chat_type": group_type,
                        "post_id": post_id
                    })
        else:
            self.main_window.show_notification("Отменено", "Сохранение отменено")


    async def save_to_db(self):
        if self.saved_to_db:
            self.main_window.show_notification("Внимание", "Данные уже добавлены в базу данных")
            return
        
        self.logger.info("Save results of parsing to database")
        await self.start_sessions()
        last_session_id = None
        s_wrapper = None
        self.start_time = datetime.now()
        self.saving = True
        self.saved_count = 0
        self.update_task = asyncio.create_task(self.sendUpdateSaveToDB())
        for user_id, (group_id, post_id, session_id, user_data) in self.existing_ids.items():
            self.logger.debug(f"Processing user to save in db {user_id}, session_id {session_id}, session_wrappers {self.session_wrappers}")
            if last_session_id != session_id:
                s_wrapper = next((wrapper for wrapper, _, sid in self.session_wrappers if sid == session_id), None)
                self.logger.debug(f"Received new wrapper for saving {s_wrapper}")
                last_session_id = session_id
            else:
                self.logger.debug(f"Does not received new wrapper, because previous is actual")
            user_data['user_id'] = user_id
            if s_wrapper:
                await s_wrapper.process_new_user(
                    user_data,
                    last_message=None,
                    user_status=4,
                    sended=False,
                    source_chat_id=group_id,
                    source_post_id=post_id
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
        self.parse_usernames = []

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
        while self._running:
            group_title, group_username, group_type = self.group_data.get(self.group_id, ("Unknown", "Unknown", "Unknown"))
            total_seconds = (datetime.now() - self.start_time).total_seconds()
            H = int(total_seconds // 3600)
            M = int((total_seconds // 60) % 60)
            S = int(total_seconds % 60)
            elapsed_time = f"{H:02}:{M:02}:{S:02}"

            self.main_window.settings_bridge.renderParsingProgressData.emit(json.dumps({
                "status": "парсинг",
                "total_count": len(self.existing_ids),
                "chat": f"{group_title} @{group_username}",
                "elapsed_time": elapsed_time
            }))

            await asyncio.sleep(UPDATE_DELAY)


    async def sendUpdateSaveToDB(self):
        parsed_count = len(self.existing_ids)
        while self.saving:
            group_title, group_username, group_type = self.group_data.get(self.group_id, ("Unknown", "Unknown", "Unknown"))
            total_seconds = (datetime.now() - self.start_time).total_seconds()
            H = int(total_seconds // 3600)
            M = int((total_seconds // 60) % 60)
            S = int(total_seconds % 60)
            elapsed_time = f"{H:02}:{M:02}:{S:02}"

            self.main_window.settings_bridge.renderParsingProgressData.emit(json.dumps({
                "status": "сохранение",
                "total_count": f"{self.saved_count}/{parsed_count}",
                "chat": f"{group_title} @{group_username}",
                "elapsed_time": elapsed_time
            }))

            await asyncio.sleep(UPDATE_DELAY)


    @property
    def running(self):
        return self._running
