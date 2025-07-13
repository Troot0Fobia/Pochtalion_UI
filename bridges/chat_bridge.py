from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QMainWindow
from qasync import asyncSlot
from telethon.errors import PeerFloodError, InputUserDeactivatedError, ForbiddenError

from .base_bridge import BaseBridge


class ChatBridge(BaseBridge):
    renderMessages = pyqtSignal(str, str, str, int, str)
    clearChatWindow = pyqtSignal()

    def __init__(self, main_window: QMainWindow, database):
        super().__init__(main_window, database)

    
    def renderNewMessage(self, msg, user, session, user_data):
        self.renderMessages.emit(msg, user, session, 1, user_data)

    
    @asyncSlot(str)
    async def sendMessage(self, message):
        session_file = self.main_window.active_session['session_file']
        error_message = f"Ошибка отправки сообщения для сессии {session_file} по причине: "
        try:
            await self.main_window.session_manager.sendMessage(
                session_file,
                self.main_window.current_chat,
                message
            )
            return
        except PeerFloodError as e:
            self.logger.error(f"{self.__class__.__name__}\tCatched Frool Error, session: {session_file}", exc_info=True)
            error_message += "Получен флуд"
        except InputUserDeactivatedError as e:
            self.logger.error(f"{self.__class__.__name__}\tCatched User Deactivated Error, session: {session_file}", exc_info=True)
            error_message += "Пользователь удален"
        except ForbiddenError as e:
            self.logger.error(f"{self.__class__.__name__}\tCatched Forbidden Error, session: {session_file}", exc_info=True)
            error_message += "Пользователь ограничил доступ"
        except Exception as e:
            self.logger.error(f"{self.__class__.__name__}\tUnexpected error while sending message, session: {session_file}", exc_info=True)
            error_message += "Неизвестная ошибка"
            
        self.main_window.show_notification("Ошибка", error_message)


    @asyncSlot(str)
    async def openVideoPlayer(self, video_path):
        from ui.video_player import VideoDialog
        try:
            dialog = VideoDialog(video_path, self.main_window)
            dialog.show()
        except Exception as e:
            self.logger.error(f"{self.__class__.__name__}\tError while opening video player", exc_info=True)