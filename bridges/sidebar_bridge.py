from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QMainWindow, QMessageBox
from qasync import asyncSlot

from .base_bridge import BaseBridge
import json


class SidebarBridge(BaseBridge):
    renderDialogs = pyqtSignal(str)
    removeDialog = pyqtSignal()
    renderSelectSessions = pyqtSignal(str)
    deleteSessionFromSelect = pyqtSignal(str)
    renderMessageNotifications = pyqtSignal(str)
    setUnreadDialog = pyqtSignal(str)

    def __init__(self, main_window: QMainWindow, database):
        super().__init__(main_window, database)
        self.current_dialog = 0


    @pyqtSlot()
    def openSettings(self):
        self.logger.info(f"{self.__class__.__name__}\tUser open settings window")
        self.main_window.openSettings()


    @asyncSlot(str)
    async def selectDialog(self, dialog_id):
        self.logger.info(f"{self.__class__.__name__}\tUser changed dialog to {dialog_id}")
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
        self.logger.info(f"{self.__class__.__name__}\tUser changed session to {session['session_file']}")
        self.main_window.active_session = session
        dialogs = await self.database.get_users_from_session(int(session['session_id']))
        if dialogs:
            unread_dialogs = self.main_window.notification_manager.get_unread_dialogs(int(session['session_id']))
            self.logger.debug(f"{self.__class__.__name__}\tCurrent session {session}\n\nCurrent dialogs: {dialogs}\n\nAnd unread dialogs: {unread_dialogs}")
            for dialog in dialogs:
                dialog['is_read'] = dialog['user_id'] not in unread_dialogs
            self.renderDialogs.emit(json.dumps(dialogs))


    @asyncSlot(str)
    async def deleteDialog(self, dialog_id_str):
        self.logger.info(f"{self.__class__.__name__}\tDeleting dialog {dialog_id_str}")
        await self.main_window.session_manager.deleteDialog(
            self.main_window.active_session['session_file'],
            int(dialog_id_str)
        )


    @pyqtSlot()
    def fetchNotifications(self):
        self.logger.info(f"{self.__class__.__name__}\tUser fetch message notifications")
        message_notifications = self.main_window.notification_manager.get_unread_messages()
        self.renderMessageNotifications.emit(json.dumps(message_notifications))