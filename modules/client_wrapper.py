from telethon import TelegramClient, events, tl, types
from core.database import Database
from pathlib import Path
from core.paths import PROFILE_PHOTOS, SESSIONS, USERS_DATA
import shutil
import io
import json
import uuid
import base64
import tzlocal
import puremagic

class ClientWrapper:
    def __init__(self, session_id: int, session_file: str, api_id: int, api_hash: str, database: Database, main_window):
        self._session_id = session_id
        self._session_file = session_file
        self._client = TelegramClient(str(SESSIONS / session_file), api_id, api_hash)
        self.database = database
        self.main_window = main_window
        self._running = False


    async def start(self) -> None:
        if self._running:
            self.main_window.show_notification("Внимание", f"Сессия {self._session_file} уже запущена")
            return
        
        await self._client.start()
        self._running = True
        me = await self._client.get_me()
        self.session_user_id = me.id
        self.is_new = await self.database.update_session(self._session_id, self.session_user_id, me.phone)
        self._register_handlers()
        # await self._fetch_dialogs()

    # def tryEnterPhone(self):
    #     print("\n\n\nNumber is needed\n\n\n")
    #     return '+0000000000'


    async def _fetch_dialogs(self):
        async for dialog in self._client.iter_dialogs():
            if not dialog.is_user:
                continue

            user = dialog.entity
            await self.process_new_user(user, dialog.message, user_status=2 if self.is_new else 0, is_read=dialog.message.out)
            
            last_id = await self.database.get_last_sync_message_id(self._session_id, user.id)
            messages = []
            current_group_id = None
            async for message in self._client.iter_messages(dialog, min_id=last_id, reverse=True):
                if message.grouped_id:
                    if current_group_id == message.grouped_id:
                        messages.append(message)
                    else:
                        if messages:
                            await self._process_new_messages(messages, user.id)
                        messages = [message]
                        current_group_id = message.grouped_id
                else:
                    if current_group_id:
                        await self._process_new_messages(messages, user.id)
                        messages = []
                        current_group_id = None
                    await self._process_new_messages([message], user.id)
            
            if messages:
                await self._process_new_messages(messages, user.id)


    async def process_new_user(self, user_entity: types.PeerUser | dict, last_message, user_status: int = None, source_chat_id: int = None, source_post_id: int = None, is_read: bool = True):
        user_id = None
        first_name = None
        last_name = None
        username = None
        phone_number = None
        profile_photo = None
        user_peer = None
        
        if isinstance(user_entity, dict):
            user_id = user_entity['user_id']
            first_name = user_entity['first_name']
            last_name = user_entity['last_name']
            username = user_entity['username']
            phone_number = user_entity['phone_number']
            user_peer = await self.client.get_input_entity(user_id)
        else:
            user_id = user_entity.id
            first_name = getattr(user_entity, 'first_name', None)
            last_name = getattr(user_entity, 'last_name', None)
            username = getattr(user_entity, 'username', None)
            phone_number = getattr(user_entity, 'phone_number', None)
            user_peer = user_entity
        
        if not (PROFILE_PHOTOS / self._session_file / f"{user_id}.jpg").exists():
            photos = await self._client.get_profile_photos(user_peer, limit=1)
            profile_photo_id = None
            profile_photo_path = None
            if photos:
                profile_photo_id = photos[0].id
                profile_photo = f"{user_id}.jpg"
                await self._client.download_media(photos[0], str(PROFILE_PHOTOS / self._session_file / profile_photo))
                ### TODO CHECK IF METHOD WILL SAVE FILE WITHOUT EXTENSION WITH ITSELF EXT
        if not await self.database.check_user_presense(user_id):
            await self.database.add_new_user(
                user_id,
                username,
                first_name,
                last_name,
                phone_number,
                profile_photo_id,
                profile_photo,
                user_status=user_status,
                sended=0 if source_chat_id or source_post_id or user_status != 5 else 1,
                source_chat_id=source_chat_id,
                source_post_id=source_post_id
            )
        if await self.database.add_user_to_session(user_id, self._session_id):
            self.main_window.sidebar_bridge.renderDialogs.emit(json.dumps([{
                "user_id": user_id,
                "first_name": first_name,
                "last_name": last_name,
                "profile_photo": profile_photo,
                "is_read": is_read,
                "last_message": last_message.message if last_message else "[New user]",
                "created_at": last_message.date.astimezone(tzlocal.get_localzone()).strftime('%d.%m.%Y %H:%M:%S') if last_message else None
            }]))

        if not is_read:
            self.main_window.notification_manager.add_unread_dialog(user_id, self.session_id)


    async def _process_new_messages(self, messages, user_id, from_event: bool = False) -> list:
        filenames = []
        mime_type = ['album'] if len(messages) > 1 else []
        render_messages = []
        for message in messages:
            if message.media:
                filename = None
                media_dir = USERS_DATA / f"{user_id}_{self._session_file}"
                media_dir.mkdir(parents=True, exist_ok=True)
                if getattr(message.media, 'document', None):
                    document = message.media.document
                    filename = f"{message.id}_{next((attr.file_name for attr in document.attributes if isinstance(attr, types.DocumentAttributeFilename)), 'unnamed')}"
                    mime_type.append(document.mime_type)
                else:
                    filename = f"{message.id}.jpg"
                    mime_type.append("image/jpeg")
                new_filename = None
                try:
                    new_filename = await message.download_media(file=str(media_dir / filename))
                except:
                    continue
                print("\n\n\nFilename:")
                print(filename)
                if new_filename:
                    filenames.append(Path(new_filename).name)
                else:
                    filenames.append(filename)

        render_messages.append({
            "message_id": messages[-1].id,
            "text": messages[0].message,
            "attachment": json.dumps(filenames) or None,
            "attachment_type": json.dumps(mime_type) or None,
            "chat_id": user_id,
            "is_out": messages[0].out,
            "created_at": messages[0].date.astimezone(tzlocal.get_localzone()).strftime('%d.%m.%Y %H:%M:%S')
        })

        if from_event:
            self.main_window.notification_manager.add_unread_dialog(user_id, self.session_id)
            self.main_window.notification_manager.add_unread_message(user_id, self.session_id, messages[0].message or "[Attachment]")
            self.main_window.sidebar_bridge.setUnreadDialog.emit(str(user_id))

        await self.database.add_new_message(
            message_id=messages[-1].id,
            text=messages[0].message,
            attachment=json.dumps(filenames) or None,
            attachment_type=json.dumps(mime_type) or None,
            chat_id=user_id,
            is_out=messages[0].out,
            session_id=self._session_id,
            created_at=messages[0].date.isoformat()
        )

        return render_messages
    

    def _register_handlers(self):
        @self._client.on(events.NewMessage)
        async def newMessage(event: tl.custom.message.Message):
            if event.grouped_id:
                return
            try:
                await self._handle_event(event, is_multiple=False)
                # chat = await event.get_chat()
                # sender = await event.get_sender()
                
                # if (isinstance(chat, (types.Channel, types.Chat)) or isinstance(sender, types.User) and sender.bot):
                #     return

                # user_id = int(sender.id)
                # await self.process_new_user(sender, event.message)
                # message = await self._process_new_messages([event.message], user_id)

                # if message and self.main_window.current_chat == user_id:
                #     self.main_window.chat_bridge.renderNewMessage(json.dumps(message), f"{user_id}_{self.session_file}")

            except Exception as e:
                print(f"Error occured while handle single message event: {e}")


        @self._client.on(events.Album)
        async def newAlbum(event):
            try:
                await self._handle_event(event, is_multiple=True)
                # chat = await event.get_chat()
                # sender = await event.get_sender()
                
                # if (isinstance(chat, (types.Channel, types.Chat)) or isinstance(sender, types.User) and sender.bot):
                #     return

                # user_id = int(sender.id)
                # await self.process_new_user(sender, event.messages[0])
                # render_messages = await self._process_new_messages(event.messages, user_id)

                # if render_messages and self.main_window.current_chat == user_id:
                #     self.main_window.chat_bridge.renderNewMessage(json.dumps(render_messages), f"{user_id}_{self.session_file}")

            except Exception as e:
                print(f"Error occured while handle multiple message event: {e}")


    async def _handle_event(self, event, is_multiple):
        chat = await event.get_chat()
        sender = await event.get_sender()
        
        if (isinstance(chat, (types.Channel, types.Chat)) or isinstance(sender, types.User) and sender.bot):
            return

        user_id = int(sender.id)
        await self.process_new_user(sender, event.messages[0] if is_multiple else event.message, user_status=0, is_read=False)
        render_messages = await self._process_new_messages(event.messages if is_multiple else [event.message], user_id, from_event=True)

        if render_messages and self.main_window.current_chat == user_id:
            self.main_window.chat_bridge.renderNewMessage(json.dumps(render_messages), f"{user_id}_{self._session_file}")


    async def sendMessage(self, user_id, message_str):
        if not self._running:
            self.main_window.show_notification("Внимание", f"Сессия {self._session_file} не запущена")
            return

        message_data = json.loads(message_str)
        b64file = message_data.get('base64_file', None)
        message_text = message_data.get('text', None)
        filename = message_data.get('filename', None)
        file_obj = None
        mime_type = []
        if b64file:
            file_obj = io.BytesIO(base64.b64decode(b64file))
            file_obj.name = filename
            mime_type = [puremagic.from_stream(file_obj, mime=True)]
            file_obj.seek(0)

        message = await self._client.send_message(
            await self._client.get_input_entity(user_id),
            message=message_text,
            file=file_obj
        )
        
        if file_obj:
            filename = f"{message.id}_{filename}"
            file_obj.seek(0)
            dir_path = USERS_DATA / f"{user_id}_{self._session_file}"
            dir_path.mkdir(parents=True, exist_ok=True)
            with open(str(dir_path / filename), 'wb') as f:
                f.write(file_obj.read())
            file_obj.close()

        await self.database.add_new_message(
            message.id,
            message_text,
            json.dumps([filename]) or None,
            json.dumps(mime_type) or None,
            user_id,
            message.out,
            self._session_id,
            message.date.isoformat()
        )

        render_message = [{
            "message_id": message.id,
            "text": message_text,
            "attachment": json.dumps([filename]) or None,
            "attachment_type": json.dumps(mime_type) or None,
            "is_out": message.out,
            "created_at": message.date.astimezone(tzlocal.get_localzone()).strftime('%d.%m.%Y %H:%M:%S')
        }]

        if message and self.main_window.current_chat == user_id:
            self.main_window.chat_bridge.renderNewMessage(json.dumps(render_message), f"{user_id}_{self._session_file}")


    async def deleteDialog(self, dialog_id: int):
        if not self._running:
            self.main_window.show_notification("Внимание", f"Сессия {self._session_file} не запущена")
            return

        await self._client.delete_dialog(await self._client.get_input_entity(dialog_id), revoke=True)
        profile_photo = await self.database.delete_user_from_session(dialog_id, self._session_id)

        shutil.rmtree(USERS_DATA / f"{dialog_id}_{self._session_file}", ignore_errors=True)
        if profile_photo:
            (PROFILE_PHOTOS / self._session_file / profile_photo).unlink(missing_ok=True)

        self.main_window.sidebar_bridge.removeDialog.emit()

        if self.main_window.current_chat == dialog_id:
            self.main_window.chat_bridge.clearChatWindow.emit()


    async def stop(self) -> None:
        if not self._running:
            return
        await self._client.disconnect()
        self._running = False


    def is_running(self) -> bool:
        return self._running


    @property
    def client(self):
        return self._client

    
    @property
    def session_file(self):
        return self._session_file


    @property
    def session_id(self):
        return self._session_id