from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QMainWindow, QMessageBox
from qasync import asyncSlot

from .base_bridge import BaseBridge
import json


class SidebarBridge(BaseBridge):
    renderDialogs = pyqtSignal(str)
    renderSelectSessions = pyqtSignal(str)
    deleteSessionFromSelect = pyqtSignal(str)
    renderMessageNotifications = pyqtSignal(str)
    setUnreadDialog = pyqtSignal(str)

    def __init__(self, main_window: QMainWindow, database):
        super().__init__(main_window, database)
        self.current_dialog = 0


    @pyqtSlot()
    def openSettings(self):
        self.main_window.openSettings()


    @asyncSlot(str)
    async def selectDialog(self, dialog_id):
        self.main_window.openChatWindow()
        user_id = int(dialog_id)
        session_id = int(self.main_window.active_session['session_id'])
        self.main_window.current_chat = user_id
        self.main_window.notification_manager.delete_unread_messages(user_id, session_id)
        self.main_window.notification_manager.delete_unread_dialog(user_id, session_id)
        messages = await self.database.get_messages_from_user(user_id, session_id)
        self.chat_bridge.renderMessages.emit(json.dumps(messages), f"{dialog_id}_{self.main_window.active_session['session_file']}", 0)


    @asyncSlot(str)
    async def changeSession(self, session_str):
        session = json.loads(session_str)
        self.main_window.active_session = session
        dialogs = await self.database.get_users_from_session(int(session['session_id']))
        if dialogs:
            unread_dialogs = self.main_window.notification_manager.get_unread_dialogs(int(session['session_id']))
            for dialog in dialogs:
                dialog['is_read'] = dialog['user_id'] not in unread_dialogs
            self.renderDialogs.emit(json.dumps(dialogs))


    @asyncSlot(str)
    async def deleteDialog(self, dialog_id_str):
        print(self.main_window.active_session)
        await self.main_window.session_manager.deleteDialog(
            self.main_window.active_session['session_file'],
            int(dialog_id_str)
        )
        print(dialog_id_str)


    @pyqtSlot()
    def fetchNotifications(self):
        message_notifications = self.main_window.notification_manager.get_unread_messages()
        print(json.dumps(message_notifications))
        self.renderMessageNotifications.emit(json.dumps(message_notifications))