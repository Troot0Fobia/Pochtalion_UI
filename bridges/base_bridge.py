from PyQt6.QtCore import QObject

from core.logger import setup_logger


class BaseBridge(QObject):

    def __init__(self, main_window, database):
        super().__init__()
        self.main_window = main_window
        self.database = database
        self.logger = setup_logger("Pochtalion.BaseBridge", "bridges.log")

    @property
    def sidebar_bridge(self):
        return self.main_window.sidebar_bridge

    @property
    def settings_bridge(self):
        return self.main_window.settings_bridge

    @property
    def chat_bridge(self):
        return self.main_window.chat_bridge
