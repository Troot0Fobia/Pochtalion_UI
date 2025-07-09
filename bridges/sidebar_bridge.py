from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QMainWindow, QMessageBox
from qasync import asyncSlot

from .base_bridge import BaseBridge
import json


class SidebarBridge(BaseBridge):
    renderDialogs = pyqtSignal(str)
    renderSelectSessions = pyqtSignal(str)
    deleteSessionFromSelect = pyqtSignal(str)

    def __init__(self, main_window: QMainWindow, database):
        super().__init__(main_window, database)
        self.current_dialog = 0


    @pyqtSlot()
    def openSettings(self):
        # self.main_window.show_warning("Ошибка", "Файл не найден!")
        self.main_window.openSettings()


    @asyncSlot(str)
    async def selectDialog(self, dialog_id):
        self.main_window.openChatWindow()
        self.main_window.current_chat = int(dialog_id)
        # print(f"Current dialog: {dialog_id}")
        # print(f"Active session: {self.main_window.active_session}")
        messages = await self.database.get_messages_from_user(int(dialog_id), int(self.main_window.active_session['session_id']))
        # print(messages)
        # print(json.dumps(messages))
        self.chat_bridge.renderMessages.emit(json.dumps(messages), f"{dialog_id}_{self.main_window.active_session['session_file']}", 0)


    @asyncSlot(str)
    async def changeSession(self, session_str):
        session = json.loads(session_str)
        self.main_window.active_session = session
        users = await self.database.get_users_from_session(int(session['session_id']))
        self.renderDialogs.emit(json.dumps(users))


    @asyncSlot(str)
    async def deleteDialog(self, dialog_id_str):
        print(self.main_window.active_session)
        await self.main_window.session_manager.deleteDialog(
            self.main_window.active_session['session_file'],
            int(dialog_id_str)
        )
        print(dialog_id_str)