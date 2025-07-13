

class NotificationManager:
    def __init__(self, main_window, database):
        self.main_window = main_window
        self.database = database
        self.unread_dialogs = {}
        self.unread_messages = set()


    async def start(self):
        self.unread_dialogs = await self.database.get_unread_dialogs()


    async def stop(self):
        await self.database.write_unread_dialogs(self.unread_dialogs)


    def add_unread_dialog(self, user_id, session_id):
        self.unread_dialogs[(user_id, session_id)] = False


    def delete_unread_dialog(self, user_id, session_id):
        self.unread_dialogs[(user_id, session_id)] = True


    def get_unread_dialogs(self, session_id):
        self.main_window.logger.debug(f"{self.__class__.__name__}\tAnd all unread dialogs: {self.unread_dialogs}")
        return {
            user_id for (user_id, _session_id), is_read in self.unread_dialogs.items() if _session_id == session_id and not is_read
        }


    def add_unread_message(self, user_id, session_id, message_text):
        self.unread_messages.add((user_id, session_id, message_text))


    def delete_unread_messages(self, user_id, session_id):
        self.unread_messages = {
            (_user_id, _session_id, _message_text) for _user_id, _session_id, _message_text in self.unread_messages if _user_id != user_id and _session_id != session_id 
        }


    def get_unread_messages(self):
        unread_messages = {}
        for user_id, session_id, message_text in self.unread_messages:
            if not unread_messages.get(session_id, None):
                unread_messages[session_id] = []
            unread_messages[session_id].append({"user_id": user_id, "message_text": message_text})
        return unread_messages
