from .client_wrapper import ClientWrapper
from core.logger import setup_logger


class SessionsManager:
    def __init__(self, api_id: int, api_hash: str, database, main_window):
        self.api_id = api_id
        self.api_hash = api_hash
        self.database = database
        self.main_window = main_window
        self.sessions = {}
        self.logger = setup_logger("Pochtalion.SessionManager", "session_manager.log")
        self.logger.info("Session Manager initialized")


    async def start_session(self, session_id: int, session_file: str) -> ClientWrapper:
        if session_file in self.sessions and self.sessions[session_file].is_running():
            return None
        self.logger.info(f"Starting session {session_file}")
        try:
            wrapper = ClientWrapper(session_id, session_file, self.api_id, self.api_hash, self.database, self.main_window)
            await wrapper.start()
            self.sessions[session_file] = wrapper
            self.main_window.settings_bridge.sessionChangedState.emit("started")
            self.logger.info(f"Session {session_file} started")
            return wrapper
        except Exception as e:
            self.logger.error(f"Error while starting session {session_file}: {e}", exc_info=True)
            self.main_window.show_notification("Ошибка", f"Ошибка во время старта сессии: {session_file}")
            return None


    async def stop_session(self, session_file: str) -> bool:
        if session_file in self.sessions:
            await self.sessions[session_file].stop()
            del self.sessions[session_file]
            self.logger.info(f"Session {session_file} stopped")
            self.main_window.settings_bridge.sessionChangedState.emit("stopped")
            return True
        return False


    async def close_sessions(self):
        self.logger.info("Closing sessions")
        for session in self.sessions.values():
            await session.stop()
        self.sessions.clear()


    def get_active_sessions(self) -> list:
        return list(self.sessions.keys())


    def get_wrapper(self, session_file: str) -> ClientWrapper:
        return self.sessions.get(session_file)


    async def sendMessage(self, session_file: str, user_id: int, message: str):
        session = self.sessions.get(session_file)
        if not session:
            self.main_window.show_notification("Внимание", f"Сессия {session_file} не запущена")
            return
        await session.sendMessage(user_id, message)

    
    async def deleteDialog(self, session_file: str, dialog_id: int):
        session = self.sessions.get(session_file)
        if not session:
            self.main_window.show_notification("Внимание", f"Сессия {session_file} не запущена")
            return
        await session.deleteDialog(dialog_id)