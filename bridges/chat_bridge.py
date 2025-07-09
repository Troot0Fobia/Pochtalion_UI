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
        await self.main_window.session_manager.sendMessage(
            self.main_window.active_session['session_file'],
            self.main_window.current_chat,
            message
        )


    @asyncSlot(str)
    async def openVideoPlayer(self, video_path):
        from videoDialog import VideoDialog
        dialog = VideoDialog(video_path, self.main_window)
        dialog.show()