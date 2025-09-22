import json
import asyncio
import re
from core.paths import SMM_IMAGES
import random
import base64
from dataclasses import dataclass
from datetime import datetime
from modules.client_wrapper import ClientWrapper
from telethon.errors import PeerFloodError, InputUserDeactivatedError, ForbiddenError, AuthKeyUnregisteredError, FloodWaitError, UsernameNotOccupiedError, ChannelPrivateError
from core.logger import setup_logger
from telethon.types import PeerUser

UPDATE_DELAY = 1

class Mailer:
    def __init__(self, main_window):
        self.main_window = main_window
        self._running = False
        self.update_task = None
        self.is_mail_from_usernames = None
        self.mail_data = None
        self.delay_between_messages = None
        self.logger = setup_logger("Pochtalion.Mailer", "mailer.log")

    @dataclass
    class SessionWrapperInfo:
        wrapper: ClientWrapper
        was_started: bool
        session_id: int
        sent_count: int = 0
        
    async def start(self, mail_data_str):
        self.logger.info("Mailing starting. Processing info")
        self.logger.debug(f"Mailing starting. Processing info: {mail_data_str}")
        mail_data = json.loads(mail_data_str)
        self.is_mail_from_usernames = mail_data['is_parse_usernames']
        self.delay_between_messages = mail_data['delay']
        self.session_files = mail_data['selected_sessions']
        self.session_wrappers = []
        self.mail_data = []
        
        self.smm_messages = await self.main_window.database.get_smm_messages()
        if not self.smm_messages:
            self.logger.info(f"User doesn't provide correct data, no mailing messages")
            self.main_window.show_notification("Внимание", "Нет сообщений для рассылки")
            return

        if self.is_mail_from_usernames:
            if not mail_data['mailing_data']:
                self.main_window.show_notification("Внимание", "Некорректные данные")
                return    
            for data in mail_data['mailing_data'].splitlines():
                matched = re.match(r'^@?(?P<username>[a-zA-Z0-9_]{5,32})$', data.strip())
                if matched:
                    self.mail_data.append({"username": matched.group('username')})
        else:
            self.mail_data = await self.main_window.database.get_users_for_sending()

        if not self.session_files or not self.delay_between_messages.isdigit():
            self.logger.info(f"User doesn't provide correct data, session files or delay between messages")
            self.main_window.show_notification("Внимание", "Некорректные данные")
            return

        if not self.mail_data:
            self.logger.info(f"User doesn't provide correct data, no data for mailing")
            self.main_window.show_notification("Внимание", "Нет пользователей для рассылки")
            return

        self.delay_between_messages = int(self.delay_between_messages or 0)
        self._running = True
        await self.start_sessions()

        index = 0
        self.sessions_count = len(self.session_wrappers)
        self.start_time = datetime.now()
        self.update_task = asyncio.create_task(self.sendUpdate())
        self.total_users_count = len(self.mail_data)

        if self.is_mail_from_usernames:
            entities = []
            for session_info in self.session_wrappers:
                if not entities:
                    entities = await session_info.wrapper.client.get_entity([data['username'] for data in self.mail_data])
                    self.logger.info("Entities received.")
                else:
                    await session_info.wrapper.client.get_entity([data['username'] for data in self.mail_data])

            self.mail_data = entities

        while self.mail_data:
            if not self._running or not self.session_wrappers:
                break

            session_info = self.session_wrappers[index % self.sessions_count]
            smm_message = random.choice(self.smm_messages)
            base64_file = None
            user_id = None
            index += 1
            
            entity = None
            if self.is_mail_from_usernames:
                entity = self.mail_data.pop()
                user_id = entity.id
                await session_info.wrapper.process_new_user(
                    {
                        "user_id": user_id,
                        "first_name": getattr(entity, 'first_name', None),
                        "last_name": getattr(entity, 'last_name', None),
                        "username": getattr(entity, 'username', None),
                        "phone_number": getattr(entity, 'phone', None)
                    },
                    last_message=None,
                    user_status=4
                )
            else:
                entity = await self.get_user_entity(self.mail_data.pop(), session_info.wrapper.client, session_info.session_id)
                if entity is None:
                    self.logger.info("No entity received from data")
                    continue
                user_id = entity.user_id
                

            self.logger.debug(f"Received entity for mailing {user_id}")
            if smm_message['photo']:
                with open(SMM_IMAGES / smm_message['photo'], 'rb') as file:
                    base64_file = base64.b64encode(file.read()).decode('utf-8')

            message = {
                "base64_file": base64_file,
                "text": smm_message['text'],
                "filename": smm_message['photo']
            }

            try:
                await session_info.wrapper.sendMessage(user_id, json.dumps(message))
            except PeerFloodError as e:
                self.logger.error(f"Catched Flood Error, stop mailing for this session {session_info.wrapper.session_file}: {e}", exc_info=True)
                await self.finish_session(session_info.session_id)
                self.main_window.show_notification("Внимание", f"Сессия {session_info.wrapper.session_file} поймала флуд")
                continue
            except InputUserDeactivatedError as e:
                self.logger.error(f"Catched User Deactivated Error, skip this user {user_id}: {e}", exc_info=True)
                continue
            except ForbiddenError as e:
                self.logger.error(f"Catched Forbidden Error, skip this user {user_id}: {e}", exc_info=True)
                continue
            except FloodWaitError as e:
                self.logger.error(f"Catched Flood Wait Error, wait for {e.seconds}", exc_info=True)
                self.main_window.show_notification("Внимание", f"Сессия {session_info.wrapper.session_file} поймала флуд, ждем {e.seconds + 10} секунд")
                await asyncio.sleep(e.seconds + 10)
            except Exception as e:
                self.logger.error(f"Unexpected error during message sending", exc_info=True)
                continue
            
            await session_info.wrapper.process_new_user(
                entity,
                smm_message['text']
            )
            # await self.main_window.database.add_user_to_session(user_id, session_info.session_id)
            session_info.sent_count += 1

            if not self.is_mail_from_usernames:
                await self.main_window.database.set_user_to_sended(user_id)

            await asyncio.sleep(self.delay_between_messages or random.randint(3, 9))

        # await self.finish_sessions()
        await self.stop()


    async def get_user_entity(self, user_data, session_client, session_id):
        self.logger.info(f"Trying get entity from user {user_data['user_id']}")
        self.logger.debug(f"Trying get entity from user {user_data} for session {session_id}")
        user_id = user_data['user_id']
        username = user_data['username']
        source_chat_id = user_data['source_chat_id']
        source_post_id = user_data['source_post_id']

        try:
            return await session_client.get_input_entity(user_id)
        except ValueError:
            pass
        except AuthKeyUnregisteredError as e:
            self.logger.error(f"Unknown error for session {session_id}", exc_info=True)
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error", exc_info=True)
            return None

        if username:
            try:
                entity = await session_client.get_entity(username)
                return await session_client.get_input_entity(entity)
            except Exception as e:
                self.logger.warning(f"Unexpected error while receiving user entity from username: {e}", exc_info=True)

        source_data = await self.main_window.database.get_parse_source(source_chat_id)
        if source_data is None:
            return None

        try:
            chat_entity = await session_client.get_entity(source_data['chat_username'])
        except UsernameNotOccupiedError as e:
            self.logger.error(f"Chat {source_data['chat_username']} was deleted. Skip it...", exc_info=True)
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error was occured. Skip user {user_id}", exc_info=True)
            return None
            
        user_entity = None

        self.logger.info(f"Received chat entity {chat_entity.id}")
        if source_data['chat_type'] == "broadcast" and source_post_id is not None:
            try:
                async for comment in session_client.iter_messages(chat_entity, reply_to=source_post_id):
                    sender = await comment.get_sender() # InputPeerUser
                    self.logger.debug(f"Received needed user for mailing of type: {type(sender)}")
                    if isinstance(sender, PeerUser) and sender.id == user_id:
                        user_entity = sender
                        # await session_client.get_input_entity(sender)
                        self.logger.info(f"Received from broadcast user entity with id: {sender.id}")
                        # await self.main_window.database.add_user_to_session(sender.user_id, session_id)
                        break
            except Exception as e:
                self.logger.error(f"Unexpected error occured. Skip group {source_data['chat_username']}", exc_info=True)
                return None
        elif source_data['chat_type'] in ("megagroup", "gigagroup", "chat"):
            if source_post_id is not None:
                message = await session_client.get_messages(chat_entity, ids=source_post_id)
                if message is not None:
                    sender = await message.get_sender()
                    if isinstance(sender, PeerUser) and sender.id == user_id:
                        user_entity = sender
                        # await session_client.get_input_entity(sender)
                        self.logger.info(f"Received from group from message {message.id} user entity with id: {sender.id}")
                        # await self.main_window.database.add_user_to_session(sender.user_id, session_id)
            else:
                try:
                    async for user in session_client.iter_participants(chat_entity):
                        if user.id == user_id:
                            user_entity = user
                            # await session_client.get_input_entity(user_entity)
                            self.logger.info(f"Received from open particitpants user entity id: {user.id}")
                            # await self.main_window.database.add_user_to_session(user_entity.id, session_id)
                            break
                except ChannelPrivateError as e:
                    self.logger.error(f"Channel privacy corrupted. Skip channel {source_data['chat_username']}", exc_info=True)
                    return None
                except Exception as e:
                    self.logger.error(f"Unexpected error occured. Skip channel {source_data['chat_username']}", exc_info=True)
                    return None

        if user_entity:
            try:
                return await session_client.get_input_entity(user_entity)
            except ValueError:
                pass

        self.logger.info("Entity was not received")
        return None


    async def stop(self):
        if not self._running:
            return
        self.logger.info("Stopping mailing")
        self._running = False
        if self.update_task:
            self.update_task.cancel()
            try:
                await self.update_task
            except asyncio.CancelledError:
                pass
        self.update_task = None
        self.main_window.settings_bridge.finishMailing.emit()
        # await self.finish_sessions()


    async def start_sessions(self):
        session_manager = self.main_window.session_manager
        if session_manager is None:
            return
        for session_id, session_file in self.session_files.items():
            session_wrapper = session_manager.get_wrapper(session_file)
            was_started = False
            if not session_wrapper:
                session_wrapper = await session_manager.start_session(session_id, session_file, is_module=True)
                was_started = True
            self.session_wrappers.append(self.SessionWrapperInfo(session_wrapper, was_started, session_id, 0))


    async def finish_session(self, session_id):
        session = next((s for s in self.session_wrappers if s.session_id == session_id), None)
        self.logger.debug(f'Finish session cause of Flood limit {session_id}\n{session}')
        if session and session.was_started:
            self.logger.debug(f"Session was started from module")
            # await self.main_window.session_manager.stop_session(session.wrapper.session_file)

        self.logger.debug(f"Before change wrappers {self.session_wrappers}")
        self.session_wrappers = [s for s in self.session_wrappers if s.session_id != session_id]
        self.logger.debug(f"After change wrappers {self.session_wrappers}")
        self.sessions_count = len(self.session_wrappers)


    # async def finish_sessions(self):
    #     for session_info in self.session_wrappers:
    #         if session_info.was_started:
    #             await self.main_window.session_manager.stop_session(session_info.wrapper.session_file)
    #     self.session_wrappers = []


    async def sendUpdate(self):
        while self._running:
            total_processed_users = sum([s.sent_count for s in self.session_wrappers])
            total_seconds = (datetime.now() - self.start_time).total_seconds()
            common_time = total_seconds * (self.total_users_count / (total_processed_users + 0.001))
            H1 = int(total_seconds // 3600)
            M1 = int((total_seconds // 60) % 60)
            S1 = int(total_seconds % 60)
            H2 = int(common_time // 3600)
            M2 = int((common_time // 60) % 60)
            S2 = int(common_time % 60)
            time = f"{H1:02}:{M1:02}:{S1:02}/{H2:02}:{M2:02}:{S2:02}"

            self.main_window.settings_bridge.renderMailingProgressData.emit(json.dumps({
                "status": "рассылка",
                "total_count": f"{total_processed_users}/{self.total_users_count}",
                "time": time
            }))

            await asyncio.sleep(UPDATE_DELAY)


    @property
    def running(self):
        return self._running