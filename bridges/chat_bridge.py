from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QMainWindow
from qasync import asyncSlot

from .base_bridge import BaseBridge


class ChatBridge(BaseBridge):
    renderMessages = pyqtSignal(str, str, int)
    clearChatWindow = pyqtSignal()

    def __init__(self, main_window: QMainWindow, database):
        super().__init__(main_window, database)

    
    def renderNewMessage(self, msg, user_session):
        self.renderMessages.emit(msg, user_session, 1)

    
    @asyncSlot(str)
    async def sendMessage(self, message):
        try:
            await self.main_window.session_manager.sendMessage(
                self.main_window.active_session['session_file'],
                self.main_window.current_chat,
                message
            )
        except Exception as e:
            self.logger.error(f"{self.__class__.__name__}\tError while sending message from session {self.main_window.active_session['session_file']}", exc_info=True)
            self.main_window.show_notification("Ошибка", "Ошибка во время отправки сообщения")


    @asyncSlot(str)
    async def openVideoPlayer(self, video_path):
        from ui.video_player import VideoDialog
        try:
            dialog = VideoDialog(video_path, self.main_window)
            dialog.show()
        except Exception as e:
            self.logger.error(f"{self.__class__.__name__}\tError while opening video player", exc_info=True)