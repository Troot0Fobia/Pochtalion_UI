import asyncio
import base64
import io
import json
import shutil
from datetime import datetime
from inspect import isawaitable
from pathlib import Path
from sqlite3 import IntegrityError

import puremagic
import tzlocal
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)
from telethon import TelegramClient, errors, events, tl, types
from telethon.errors import (
    ApiIdInvalidError,
    ApiIdPublishedFloodError,
    FileMigrateError,
    PasswordHashInvalidError,
    TakeoutInitDelayError,
    UsernameInvalidError,
)

from core.database import Database
from core.paths import PROFILE_PHOTOS, SESSIONS, TMP, USERS_DATA
from ui.auth_window import AuthWindow
from ui.qr_login import QRLoginWindow


class AuthCanceled(Exception):
    pass


class ClientWrapper:

    def __init__(
        self,
        session_id: int,
        session_file: str,
        api_id: int,
        api_hash: str,
        database: Database,
        main_window,
        logger,
    ):
        self._session_id = int(session_id)
        self._session_file = session_file
        self._client = TelegramClient(str(SESSIONS / session_file), api_id, api_hash)
        self.database = database
        self.main_window = main_window
        self.logger = logger
        self.auth_window = AuthWindow(main_window, session_file)
        self._status = 0  # 0 - not running | 1 - running | 2 - processing
        self.is_new = True

    async def start(
        self, phone_number: str | None = None, is_module: bool = False
    ) -> bool:
        if self._status:
            self.main_window.show_notification(
                "Внимание", f"Сессия {self._session_file} уже запущена"
            )
            return False
        self._status = 2
        try:
            if phone_number:
                start_func = self._client.start(
                    phone=phone_number or self.phone_callback,
                    code_callback=self.code_callback,
                    password=self.password_callback,
                )
                if isawaitable(start_func):
                    await start_func
            else:
                await self.login_qr()
        except AuthCanceled:
            self.logger.warning(f"{self.session_file}\tUser cancelled authentication")
            self.auth_window.close()
            return False
        except PasswordHashInvalidError as e:
            self.logger.warning(f"{self.session_file}\tInvalid password provided: {e}")
            self.auth_window.close()
            self.main_window.show_notification("Ошибка", "Неверный пароль")
            return False
        except ApiIdInvalidError as e:
            self.logger.warning(f"{self.session_file}\tInvalid api_id provided: {e}")
            self.auth_window.close()
            self.main_window.show_notification("Ошибка", "API id невалидный")
            return False
        except ApiIdPublishedFloodError as e:
            self.logger.warning(
                f"{self.session_file}\tAPI id is catched flood error: {e}"
            )
            self.auth_window.close()
            self.main_window.show_notification("Ошибка", "API id поймал флуд")
            return False
        except Exception as e:
            self.logger.error(
                f"{self.session_file}\tUnexpected error: {e}", exc_info=True
            )
            self.auth_window.close()
            return False

        self.auth_window.close()

        me = await self._client.get_me(input_peer=False)
        if isinstance(me, types.User):
            self.session_user_id = me.id
        elif isinstance(me, types.InputPeerUser):
            self.session_user_id = me.user_id
        else:
            self.main_window.show_notification(
                "Ошибка", "Не удалось получить сущность сессии"
            )
            return False

        try:
            self.is_new = await self.database.update_session(
                self._session_id, self.session_user_id, getattr(me, "phone", "")
            )
        except IntegrityError as e:
            self.logger.error(
                f"{self.session_file}\tSqlite raised error", exc_info=True
            )
            # Test validation
            if "UNIQUE" in str(e):
                self.main_window.show_notification(
                    "Ошибка", "Такая сессия уже существует"
                )
        self._register_handlers()

        if (
            self.main_window.settings_manager.get_setting("fetch_sessions_old_dialogs")
            and not is_module
        ):
            await self.fetch_dialogs()
        self._status = 1
        return True

    async def login_qr(self):
        await self._client.connect()

        if await self._client.is_user_authorized():
            return

        qr_login = QRLoginWindow()
        tries = 0
        while True:
            qr_login.update_status("Generating QR")
            qr = await self._client.qr_login()

            qr_login.fill_qr(qr.url)
            qr_login.update_status("Scan qr code with your phone")

            try:
                await qr.wait(timeout=120)
                qr_login.update_status("QR login successful")
                break
            except asyncio.TimeoutError:
                qr_login.update_status("Timeout. Wait for refresh QR")
                tries += 1
                if tries > 3:
                    return
            except errors.SessionPasswordNeededError:
                password = await self.password_callback()
                await self._client.sign_in(password=password)
                break
            except Exception as e:
                qr_login.update_status("Unexpected error occured")
                self.logger.error(
                    f"Error occured while auth with qr code: {e}", exc_info=True
                )
                break

            await asyncio.sleep(0.3)

        qr_login.exit()

    async def phone_callback(self):
        phone = await self.auth_window.get_input_async()
        if phone is None:
            raise AuthCanceled()
        return phone

    async def code_callback(self):
        self.auth_window.next_step("code")
        return await self.auth_window.get_input_async()

    async def password_callback(self):
        self.auth_window.next_step("password")
        return await self.auth_window.get_input_async()

    async def fetch_dialogs(self) -> None:
        try:
            async with self._client.takeout(users=True) as takeout:
                async for dialog in takeout.iter_dialogs():
                    if not dialog.is_user:
                        continue

                    self.logger.debug(f"{self.session_file}\t{dialog}")
                    user_id = dialog.id
                    messages = []
                    last_id = 0
                    is_user_exists = await self.database.check_user_presense(user_id)

                    if is_user_exists:
                        last_id = await self.database.get_last_sync_message_id(
                            self._session_id, user_id
                        )
                        self.logger.debug(
                            f"{self.session_file}\tLast message id from existed user {last_id}"
                        )
                    else:
                        last_id = getattr(dialog.message, "id", 10) - 10
                        self.logger.debug(
                            f"{self.session_file}\tLast message id from new user {last_id}"
                        )

                    await self.process_new_user(
                        dialog.entity,
                        dialog.message,
                        user_status=2 if self.is_new else 0,
                        sended=True,
                        is_read=dialog.message.out,
                    )

                    current_group_id = None
                    async for message in self._client.iter_messages(
                        dialog, min_id=last_id, reverse=True
                    ):
                        self.logger.debug(f"{self.session_file}\t{message}")
                        if message.grouped_id:
                            if current_group_id == message.grouped_id:
                                messages.append(message)
                            else:
                                if messages:
                                    await self._process_new_messages(messages, user_id)
                                messages = [message]
                                current_group_id = message.grouped_id
                        else:
                            if current_group_id:
                                await self._process_new_messages(messages, user_id)
                                messages = []
                                current_group_id = None
                            await self._process_new_messages([message], user_id)

                    if messages:
                        await self._process_new_messages(messages, user_id)
        except TakeoutInitDelayError as e:
            self.logger.error(
                f"Takeout rate limit. Must wait {e.seconds}: {e}", exc_info=True
            )
        except Exception as e:
            self.logger.error(
                f"Unexpected error ocurred while retrieving dialogs: {e}", exc_info=True
            )
            self.main_window.show_notification("Ошибка", "Ошибка получения диалогов")

    async def fetch_voice_dialogs(self) -> list[dict]:
        try:
            async with self._client.takeout(users=True) as takeout:
                dialogs = []
                session_dialogs = await takeout.get_dialogs(
                    ignore_migrated=True, archived=False
                )
                for dialog in session_dialogs:
                    if (
                        dialog.is_user
                        and dialog.title.strip()
                        and dialog.name != "Telegram"
                        and not dialog.entity.bot
                        and dialog.id != self.session_user_id
                    ):
                        dialogs.append({"id": dialog.id, "title": dialog.title.strip()})

                return dialogs
        except TakeoutInitDelayError as e:
            self.logger.error(
                f"Takeout rate limit. Must wait {e.seconds}: {e}", exc_info=True
            )
            self.main_window.show_notification(
                "Вниманhие", f"Частые запросы. Нужно подождать {e.seconds}"
            )
        except Exception as e:
            self.logger.error(
                f"Unexpected error ocurred while retrieving voice dialogs: {e}",
                exc_info=True,
            )
            self.main_window.show_notification("Ошибка", "Ошибка получения диалогов")

        return []

    async def fetch_voices(self, user_id: int) -> list:
        try:
            async with self._client.takeout(
                files=True, max_file_size=5000000
            ) as takeout:
                messages = await takeout.get_messages(
                    user_id, limit=100, filter=types.InputMessagesFilterVoice
                )

                if not messages:
                    return []

                folder = TMP / self._session_file / str(user_id)
                folder.mkdir(parents=True, exist_ok=True)

                voices = []
                for message in messages:
                    message_id = message.id
                    filename = f"{message_id}_voice"
                    file = await message.download_media(file=str(folder / filename))
                    voices.append(
                        {
                            "id": message_id,
                            "path": file,
                        }
                    )

                return voices

        except Exception as e:
            self.logger.error(
                f"Unexpected error occured while retrieving voices from dialog {user_id}: {e}",
                exc_info=True,
            )
            self.main_window.show_notification("Ошибка", "Ошибка получения голосовых")

        return []

    async def process_new_user(
        self,
        user_entity: types.InputPeerUser | types.User | dict,
        last_message,
        user_status: int = 0,
        sended: bool = False,
        source_chat_id: int | None = None,
        source_post_id: int | None = None,
        is_read: bool = True,
    ):
        user_id = None
        first_name = None
        last_name = None
        username = None
        phone_number = None
        profile_photo = ""
        user_peer = None
        profile_photo_id = None

        if isinstance(user_entity, dict):
            user_id = user_entity["user_id"]
            first_name = user_entity["first_name"]
            last_name = user_entity["last_name"]
            username = user_entity["username"]
            phone_number = user_entity["phone_number"]
            try:
                user_peer = await self.client.get_input_entity(user_id)
            except Exception as e:
                self.logger.error(
                    f"Error receiving user input entity {user_id} from session {self._session_id}: {e}",
                    exc_info=True,
                )
                return
        elif isinstance(user_entity, types.User):
            user_id = user_entity.id
            first_name = getattr(user_entity, "first_name", None)
            last_name = getattr(user_entity, "last_name", None)
            username = getattr(user_entity, "username", None)
            phone_number = getattr(user_entity, "phone", None)
            user_peer = user_entity
        elif isinstance(user_entity, types.InputPeerUser):
            user_id = user_entity.user_id
            user_peer = user_entity

        profile_photo = await self.database.get_user_photo(user_id)
        profile_photo_path = (
            PROFILE_PHOTOS / self._session_file if user_status != -1 else TMP
        )
        if not profile_photo or (
            profile_photo and not (profile_photo_path / profile_photo).exists()
        ):
            try:
                photos = await self._client.get_profile_photos(user_peer, limit=1)
                if photos:
                    profile_photo_id = photos[0].id
                    profile_photo = str(user_id)
                    profile_photo = await self._client.download_media(
                        photos[0], str(profile_photo_path / profile_photo)
                    )
                    if profile_photo and isinstance(profile_photo, str):
                        profile_photo = Path(profile_photo).name
            except FileMigrateError as e:
                self.logger.error(
                    f"Error while downloading user photo. File was migrated to another server: {e}",
                    exc_info=True,
                )
            except Exception as e:
                self.logger.error(
                    f"Unexpected error occured while donwloading users profile photo. User id: {user_id}: {e}",
                    exc_info=True,
                )

        if user_status == -1:
            return {
                "user_id": user_id,
                "first_name": first_name,
                "last_name": last_name,
                "user_full_name": f"{first_name} {last_name}",  # TODO maybe fix it
                "username": username,
                "phone_number": phone_number,
                "profile_photo": profile_photo,
            }

        if not isinstance(user_entity, types.InputPeerUser):
            await self.database.add_new_user(
                user_id,
                username,
                first_name,
                last_name,
                phone_number,
                profile_photo_id,
                profile_photo,
                user_status=user_status,
                sended=sended,
                source_chat_id=source_chat_id,
                source_post_id=source_post_id,
            )
        if await self.database.add_user_to_session(user_id, self._session_id):
            self.logger.debug(
                (
                    f"{self.session_file}\tActive session while processing new user "
                    f"{self.main_window.active_session} and current session id: {self._session_id}"
                )
            )
            if self.main_window.active_session["session_id"] == self._session_id:
                if isinstance(user_entity, types.InputPeerUser):
                    first_name, last_name, profile_photo = (
                        await self.database.get_user_data(user_id)
                    )
                created_at = (
                    datetime.now()
                    .astimezone(tzlocal.get_localzone())
                    .strftime("%d.%m.%Y %H:%M:%S"),
                )
                if hasattr(last_message, "message"):
                    last_message = last_message.message
                    if hasattr(last_message, "date"):
                        created_at = last_message.date.astimezone(
                            tzlocal.get_localzone()
                        ).strftime("%d.%m.%Y %H:%M:%S")
                elif isinstance(last_message, str):
                    pass
                else:
                    last_message = "[New user]"
                self.main_window.sidebar_bridge.renderDialogs.emit(
                    json.dumps(
                        [
                            {
                                "user_id": user_id,
                                "first_name": first_name,
                                "last_name": last_name,
                                "profile_photo": profile_photo,
                                "username": username,
                                "status": user_status,
                                "is_read": is_read,
                                "last_message": last_message,
                                "created_at": created_at,
                            }
                        ]
                    )
                )

        if not is_read:
            self.main_window.notification_manager.add_unread_dialog(
                user_id, self._session_id
            )

    async def _process_new_messages(
        self, messages, user_id, from_event: bool = False
    ) -> list:
        filenames = []
        mime_type = ["album"] if len(messages) > 1 else []
        render_messages = []
        for message in messages:
            media = message.media
            if media:
                filename = None
                new_filename = None
                media_dir = USERS_DATA / f"{user_id}_{self._session_file}"
                media_dir.mkdir(parents=True, exist_ok=True)
                if isinstance(media, types.MessageMediaContact):
                    filenames.append(
                        json.dumps(
                            {
                                "phone_number": getattr(media, "phone_number", None),
                                "first_name": getattr(media, "first_name", None),
                                "last_name": getattr(media, "last_name", None),
                                "user_id": str(getattr(media, "user_id", "")),
                            }
                        )
                    )
                    mime_type.append("contact")
                else:
                    if getattr(message.media, "document", None):
                        document = message.media.document
                        filename_atr = next(
                            (
                                attr.file_name
                                for attr in document.attributes
                                if isinstance(attr, types.DocumentAttributeFilename)
                            ),
                            "unnamed",
                        )
                        filename = f"{message.id}_{filename_atr}"
                        mime_type.append(document.mime_type)
                    else:
                        filename = f"{message.id}.jpg"
                        mime_type.append("image/jpeg")
                    try:
                        new_filename = await message.download_media(
                            file=str(media_dir / filename)
                        )
                    except Exception:
                        continue

                    if new_filename:
                        filenames.append(Path(new_filename).name)
                    else:
                        filenames.append(filename)

        render_messages.append(
            {
                "message_id": messages[-1].id,
                "text": messages[0].message,
                "attachment": json.dumps(filenames) or None,
                "attachment_type": json.dumps(mime_type) or None,
                "chat_id": user_id,
                "is_out": messages[0].out,
                "created_at": messages[0]
                .date.astimezone(tzlocal.get_localzone())
                .strftime("%d.%m.%Y %H:%M:%S"),
            }
        )

        if from_event:
            self.main_window.notification_manager.add_unread_dialog(
                user_id, self._session_id
            )
            self.main_window.notification_manager.add_unread_message(
                user_id, self._session_id, messages[0].message or "[Attachment]"
            )
            self.main_window.sidebar_bridge.setUnreadDialog.emit(str(user_id))

        await self.database.add_new_message(
            message_id=messages[-1].id,
            text=messages[0].message,
            attachment=json.dumps(filenames) or "",
            attachment_type=json.dumps(mime_type) or "",
            chat_id=user_id,
            is_out=messages[0].out,
            session_id=self._session_id,
            created_at=messages[0].date.isoformat(),
        )

        return render_messages

    def _register_handlers(self):
        @self._client.on(events.NewMessage)
        async def newMessage(event: tl.custom.message.Message):
            if event.grouped_id:
                return
            try:
                await self._handle_event(event, is_multiple=False)
            except Exception as e:
                self.logger.error(
                    f"{self.session_file}\tError occured while handle single message event: {e}",
                    exc_info=True,
                )

        @self._client.on(events.Album)
        async def newAlbum(event):
            try:
                await self._handle_event(event, is_multiple=True)
            except Exception as e:
                self.logger.error(
                    f"{self.session_file}\tError occured while handle multiple message event: {e}",
                    exc_info=True,
                )

    async def _handle_event(self, event, is_multiple):
        chat = await event.get_chat()
        sender = await event.get_sender()

        if (
            isinstance(chat, (types.Channel, types.Chat))
            or isinstance(sender, types.User)
            and sender.bot
        ):
            return

        user_id = int(sender.id)
        await self.process_new_user(
            sender,
            event.messages[0] if is_multiple else event.message,
            user_status=0,
            sended=True,
            is_read=False,
        )
        render_messages = await self._process_new_messages(
            event.messages if is_multiple else [event.message], user_id, from_event=True
        )

        if render_messages and self.main_window.current_chat == user_id:
            self.main_window.chat_bridge.renderNewMessage(
                json.dumps(render_messages), str(sender.id), self._session_file, r"{}"
            )

    async def sendMessage(self, user_id, message_str, voice: bool = False):
        if not self._status:
            self.main_window.show_notification(
                "Внимание", f"Сессия {self._session_file} не запущена"
            )
            return

        message_data = json.loads(message_str)
        filename = message_data.get("filename", None)
        message_text = message_data.get("text", None)

        if voice:
            voice_path = message_data["path"]
            mime_type = ["audio/ogg"]

            message = await self._client.send_file(
                await self._client.get_input_entity(user_id),
                file=voice_path,
                voice_note=True,
            )
            if isinstance(message, list):
                message = message[0]

            filename = f"{message.id}_voice{Path(voice_path).suffix}"
            user_session_dir_path = USERS_DATA / f"{user_id}_{self._session_file}"
            user_session_dir_path.mkdir(parents=True, exist_ok=True)

            shutil.copy(
                voice_path,
                user_session_dir_path / filename,
            )
        else:
            b64file = message_data.get("base64_file", None)
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
                file=file_obj.getvalue() if file_obj else None,
            )

            if file_obj:
                filename = f"{message.id}_{filename}"
                file_obj.seek(0)
                dir_path = USERS_DATA / f"{user_id}_{self._session_file}"
                dir_path.mkdir(parents=True, exist_ok=True)
                with open(str(dir_path / filename), "wb") as f:
                    f.write(file_obj.read())
                file_obj.close()

        if hasattr(message, "date") and message.date:
            message_time = message.date.isoformat()
            render_time = message.date.astimezone(tzlocal.get_localzone()).strftime(
                "%d.%m.%Y %H:%M:%S"
            )
        else:
            message_time = (
                datetime.now()
                .astimezone(tzlocal.get_localzone())
                .strftime("%d.%m.%Y %H:%M:%S")
            )
            render_time = message_time
        await self.database.add_new_message(
            message.id,
            message_text,
            json.dumps([filename]) or "",
            json.dumps(mime_type) or "",
            user_id,
            message.out or False,
            self._session_id,
            message_time,
        )

        render_message = [
            {
                "message_id": message.id,
                "text": message_text,
                "attachment": json.dumps([filename]) or None,
                "attachment_type": json.dumps(mime_type) or None,
                "is_out": message.out,
                "created_at": render_time,
            }
        ]

        if message and self.main_window.current_chat == user_id:
            self.main_window.chat_bridge.renderNewMessage(
                json.dumps(render_message), str(user_id), self._session_file, r"{}"
            )

    async def deleteDialog(self, dialog_id: int):
        if not self._status:
            self.main_window.show_notification(
                "Внимание", f"Сессия {self._session_file} не запущена"
            )
            return

        await self._client.delete_dialog(
            await self._client.get_input_entity(dialog_id), revoke=True
        )
        profile_photo = await self.database.delete_user_from_session(
            dialog_id, self._session_id
        )

        shutil.rmtree(
            USERS_DATA / f"{dialog_id}_{self._session_file}", ignore_errors=True
        )
        if profile_photo:
            (PROFILE_PHOTOS / self._session_file / profile_photo).unlink(
                missing_ok=True
            )

        self.main_window.sidebar_bridge.removeDialog.emit()

        if self.main_window.current_chat == dialog_id:
            self.main_window.chat_bridge.clearChatWindow.emit()

    # TODO remake this method

    async def searchUsername(self, username):
        try:
            entity = await self._client.get_entity(username)
        except UsernameInvalidError as e:
            self.logger.error(
                f"{self._session_file}\tUsername does not exist: {e}", exc_info=True
            )
            self.main_window.show_notification(
                "Внимание", f"Такой username '{username}' не существует"
            )
            return
        user_data = None
        if not isinstance(entity, types.User):
            self.main_window.show_notification(
                "Внимание", f"Сущность с username '{username}' не пользователь"
            )
        else:
            if entity.bot or entity.deleted:
                self.main_window.show_notification(
                    "Внимание",
                    f"Пользователь с username '{username}' или бот, или удален",
                )
            else:
                user_data = await self.process_new_user(
                    entity, last_message=None, user_status=-1
                )

        if user_data:
            dialog = UserInfoDialog(user_data)
            result = dialog.exec()

            if result == 2:
                await self.process_new_user(user_data, None, user_status=6)
                await self.main_window.sidebar_bridge.selectDialog(
                    str(user_data["user_id"]), json.dumps(user_data)
                )

    async def stop(self) -> None:
        if not self._status:
            return
        if self._client and self._client.is_connected:
            if isawaitable(disconnect_func := self._client.disconnect()):
                await disconnect_func
        self._status = 0

    def status(self) -> bool:
        return bool(self._status)

    @property
    def client(self):
        return self._client

    @property
    def session_file(self):
        return self._session_file

    @property
    def session_id(self):
        return self._session_id


# TODO Remake this window
class UserInfoDialog(QDialog):

    def __init__(self, user_data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Информация о пользователе")
        self.setModal(True)
        self.setFixedSize(400, 300)

        layout = QVBoxLayout()
        grid = QGridLayout()

        # Фото профиля
        image_label = QLabel()
        profile_path = TMP / user_data.get("profile_photo", "")
        if profile_path.exists():
            pixmap = QPixmap(str(profile_path))
            image_label.setPixmap(
                pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio)
            )
        else:
            image_label.setText("Фото отсутствует")
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Информация
        grid.addWidget(QLabel("ID:"), 0, 0)
        grid.addWidget(QLabel(str(user_data["user_id"])), 0, 1)

        grid.addWidget(QLabel("Имя:"), 1, 0)
        grid.addWidget(QLabel(user_data["user_full_name"]), 1, 1)

        grid.addWidget(QLabel("Username:"), 2, 0)
        grid.addWidget(
            QLabel("@" + user_data["username"] if user_data["username"] else "-"), 2, 1
        )

        grid.addWidget(QLabel("Телефон:"), 3, 0)
        grid.addWidget(QLabel(user_data["phone_number"] or "-"), 3, 1)

        # Кнопки
        button_box = QDialogButtonBox()
        write_btn = QPushButton("Написать пользователю")
        ok_btn = QPushButton("Ок")

        button_box.addButton(write_btn, QDialogButtonBox.ButtonRole.ActionRole)
        button_box.addButton(ok_btn, QDialogButtonBox.ButtonRole.AcceptRole)

        write_btn.clicked.connect(self.write_to_user)
        ok_btn.clicked.connect(self.accept)

        layout.addWidget(image_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(grid)
        layout.addSpacing(10)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def write_to_user(self):
        print("Написать пользователю нажато")
        self.done(2)  # Можно вернуть код 2 для обработки
