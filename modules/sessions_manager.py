from core.logger import setup_logger

from .client_wrapper import ClientWrapper


class SessionsManager:

    def __init__(self, api_id: int, api_hash: str, database, main_window):
        self.api_id = api_id
        self.api_hash = api_hash
        self.database = database
        self.main_window = main_window
        self.sessions: dict[str, ClientWrapper] = {}
        self.logger = setup_logger("Pochtalion.SessionManager", "session_manager.log")
        self.logger.info("Session Manager initialized")

    async def start_session(
        self,
        session_id: int,
        session_file: str,
        phone_number: str | None = None,
        is_module: bool = False,
    ) -> ClientWrapper | None:
        if session_file in self.sessions and self.sessions[session_file].status():
            return None
        self.logger.info(f"Starting session {session_file}")
        try:
            wrapper = ClientWrapper(
                session_id,
                session_file,
                self.api_id,
                self.api_hash,
                self.database,
                self.main_window,
                self.logger,
            )
            result = await wrapper.start(phone_number, is_module)
            if not result:
                self.main_window.settings_bridge.sessionChangedState.emit(
                    str(session_id), "stopped"
                )
                if session_file in self.sessions:
                    del self.sessions[session_file]
                return None

            self.sessions[session_file] = wrapper
            self.main_window.settings_bridge.sessionChangedState.emit(
                str(session_id), "started"
            )
            self.logger.info(f"Session {session_file} started")
            return wrapper
        except Exception as e:
            self.logger.error(
                f"Error while starting session {session_file}: {e}", exc_info=True
            )
            self.main_window.show_notification(
                "Ошибка", f"Ошибка во время старта сессии: {session_file}"
            )
            return None

    async def stop_session(self, session_file: str) -> bool:
        if session_file in self.sessions:
            session_id = self.sessions[session_file].session_id
            await self.sessions[session_file].stop()
            del self.sessions[session_file]
            self.logger.info(f"Session {session_file} stopped")
            self.main_window.settings_bridge.sessionChangedState.emit(
                str(session_id), "stopped"
            )
            return True
        return False

    async def close_sessions(self):
        self.logger.info("Closing sessions")
        for session in self.sessions.values():
            await session.stop()
        self.sessions.clear()

    def get_active_sessions(self) -> dict:
        return {
            session_file: wrapper.status()
            for session_file, wrapper in self.sessions.items()
        }

    def get_wrapper(self, session_file: str) -> ClientWrapper | None:
        return self.sessions.get(session_file, None)

    async def sendMessage(self, session_file: str, user_id: int, message: str):
        session = self.sessions.get(session_file)
        if not session:
            self.main_window.show_notification(
                "Внимание", f"Сессия {session_file} не запущена"
            )
            return
        await session.sendMessage(user_id, message)

    async def get_or_start_session(
        self, session_id: int, session_file: str
    ) -> ClientWrapper | None:
        session_wrapper = None

        if session_file not in self.sessions:
            session_wrapper = await self.start_session(session_id, session_file)
        else:
            session_wrapper = self.sessions.get(session_file)

        return session_wrapper

    async def get_session_dialogs(
        self, session_id: int, session_file: str
    ) -> list[dict]:
        if session_wrapper := await self.get_or_start_session(session_id, session_file):
            return await session_wrapper.fetch_voice_dialogs()

        return []

    async def get_dialog_voices(
        self, session_id: int, session_file: str, dialog_id: int
    ) -> list[dict]:
        if session_wrapper := await self.get_or_start_session(session_id, session_file):
            return await session_wrapper.fetch_voices(dialog_id)

        return []

    async def deleteDialog(self, session_file: str, dialog_id: int):
        session = self.sessions.get(session_file)
        if not session:
            self.main_window.show_notification(
                "Внимание", f"Сессия {session_file} не запущена"
            )
            return
        await session.deleteDialog(dialog_id)

