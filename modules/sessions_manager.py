from .client_wrapper import ClientWrapper


class SessionsManager:
    def __init__(self, api_id: int, api_hash: str, database, main_window):
        self.api_id = api_id
        self.api_hash = api_hash
        self.database = database
        self.main_window = main_window
        self.sessions = {}


    async def start_session(self, session_id: int, session_file: str) -> ClientWrapper:
        if session_file in self.sessions and self.sessions[session_file].is_running():
            return None

        wrapper = ClientWrapper(session_id, session_file, self.api_id, self.api_hash, self.database, self.main_window)
        await wrapper.start()
        self.sessions[session_file] = wrapper
        return wrapper


    async def stop_session(self, session_file: str) -> bool:
        print("stop session")
        print(self.sessions)
        if session_file in self.sessions:
            await self.sessions[session_file].stop()
            del self.sessions[session_file]
            return True
        return False


    async def close_sessions(self):
        print("sessions in manager")
        print(self.sessions)
        for session_file, session in self.sessions.items():
            await session.stop()
            del self.sessions[session_file]


    def get_active_sessions(self) -> list:
        return list(self.sessions.keys())


    def get_wrapper(self, session_file: str) -> ClientWrapper:
        return self.sessions.get(session_file)


    async def sendMessage(self, session_file: str, user_id: int, message: str):
        session = self.sessions.get(session_file)
        if not session:
            self.main_window.show_warning("Внимание", f"Сессия {session_file} не запущена")
            return
        await session.sendMessage(user_id, message)

    
    async def deleteDialog(self, session_file: str, dialog_id: int):
        session = self.sessions.get(session_file)
        if not session:
            self.main_window.show_warning("Внимание", f"Сессия {session_file} не запущена")
            return
        await session.deleteDialog(dialog_id)