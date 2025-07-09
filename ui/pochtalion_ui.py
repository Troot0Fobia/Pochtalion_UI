import json
import pathlib
import asyncio
import os

from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QSplitter, QStackedWidget, QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl, QSize, Qt
from core.database import Database
from bridges import chat_bridge, settings_bridge, sidebar_bridge
from modules.sessions_manager import SessionsManager
from qasync import asyncClose, asyncSlot
from core.paths import WEB
from modules.parser import Parser
from modules.mailer import Mailer
from core.notification_manager import NotificationManager


class Pochtalion_UI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pochtalion")
        self.setMinimumSize(QSize(600, 800))
        self.current_chat = None
        self.active_session = None

        self.sidebar_window = QWebEngineView()
        self.chat_window = QWebEngineView()
        self.settings_window = QWebEngineView()
        self.parser = Parser(self)
        self.mailer = Mailer(self)

        self.database = None
        
    @asyncSlot()
    async def init_async(self):
        self.database = await Database.create()
        self.session_manager = SessionsManager(29572409, 'b882aac92b82a94c7dc21ccf80b42e4e', self.database, self)
        self.notification_manager = NotificationManager(self, self.database)
        await self.notification_manager.start()

        ### Chat init ###
        self.chat_bridge = chat_bridge.ChatBridge(self, self.database)
        self.chat_channel = QWebChannel()
        self.chat_channel.registerObject("chatBridge", self.chat_bridge)
        self.chat_window.setUrl(QUrl.fromLocalFile(str(WEB / 'chat.html')))
        self.chat_window.page().setWebChannel(self.chat_channel)

        ### Sidebar init ###
        self.sidebar_bridge = sidebar_bridge.SidebarBridge(self, self.database)
        self.sidebar_channel = QWebChannel()
        self.sidebar_channel.registerObject("sidebarBridge", self.sidebar_bridge)
        self.sidebar_window.setUrl(QUrl.fromLocalFile(str(WEB / 'sidebar.html')))
        self.sidebar_window.page().setWebChannel(self.sidebar_channel)

        ### Settings init ###
        self.settings_bridge = settings_bridge.SettingsBridge(self, self.database)
        self.settings_channel = QWebChannel()
        self.settings_channel.registerObject("settingsBridge", self.settings_bridge)
        self.settings_window.setUrl(QUrl.fromLocalFile(str(WEB / 'settings.html')))
        self.settings_window.page().setWebChannel(self.settings_channel)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.chat_window)
        self.stack.addWidget(self.settings_window)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar_window)
        self.splitter.addWidget(self.stack)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)

        self.main_widget = QWidget()
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.addWidget(self.splitter)
        self.setCentralWidget(self.main_widget)

        self.sidebar_window.loadFinished.connect(
            lambda _: asyncio.create_task(self.loadSidebar())
        )
        
        # self.notification_manager.add_unread_message(1, 123, "Text")
        # self.notification_manager.add_unread_message(2, 123, "MEssage")
        # self.notification_manager.add_unread_message(1, 123, "For")
        # self.notification_manager.add_unread_message(2, 121, "Test")
        # self.notification_manager.add_unread_message(1, 121, "Some test message")
        # self.notification_manager.add_unread_message(1, 123, "For event")
        # self.notification_manager.add_unread_message(1, 122, "Notification attached")
        # self.notification_manager.add_unread_message(1, 122, "[Attachment]")
        # self.notification_manager.add_unread_message(4237, 121, "[Attachment]")
        return self


    async def loadSidebar(self):
        sessions = await self.database.get_sessions()
        if sessions:
            # print(sessions)
            self.active_session = sessions[0]
            self.sidebar_bridge.renderSelectSessions.emit(json.dumps(sessions))

            dialogs = await self.database.get_users_from_session(sessions[0]['session_id'])
            if dialogs:
                unread_dialogs = self.notification_manager.get_unread_dialogs(sessions[0]['session_id'])
                for dialog in dialogs:
                    dialog['is_read'] = dialog['user_id'] not in unread_dialogs
                self.sidebar_bridge.renderDialogs.emit(json.dumps(dialogs))


    def openSettings(self):
        self.stack.setCurrentWidget(self.settings_window)

    
    def openChatWindow(self):
        self.stack.setCurrentWidget(self.chat_window)


    # async def startSession(self, session_str):
    #     session = json.loads(session_str)
    #     await self.session_manager.start_session(session['session_id'], session['session_name'])


    # async def stopSession(self, session_file):
    #     await self.session_manager.stop_session(session_file)


    @asyncClose
    async def closeEvent(self, event):
        print("closing application")
        await self.parser.stop()
        await self.mailer.stop()
        await self.notification_manager.stop()
        await self.database.closeConnetion()
        await self.session_manager.close_sessions()
        self.chat_window.deleteLater()
        self.sidebar_window.deleteLater()
        self.settings_window.deleteLater()
        QApplication.quit()
        event.accept()


    def show_notification(self, title, message):
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.setModal(False)
        msg.show()


# API_ID = '29572409'
# API_HASH = 'b882aac92b82a94c7dc21ccf80b42e4e'