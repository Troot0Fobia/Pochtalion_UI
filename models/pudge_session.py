from typing import Any


class PudgeSession:

    def __init__(self, session_file: str):
        self.session_file: str = session_file
        self.client_wrapper: Any = None
        self.handler: Any = None                 # registered Telethon event handler
        self.running: bool = False
        self.starting: bool = False
        self.send_to_saved: bool = False
        self.target_group: str = ""
        self.hook_ids: list[int] = []            # IDs of selected hook_messages rows
        self.groups: list[str] = []              # normalised group identifiers to monitor
        self.monitored_chat_ids: set[int] = set()   # resolved numeric IDs (groups + channels)
        self.discussion_chat_ids: set[int] = set()  # linked discussion group IDs for channels
        self.received_count: int = 0

    def set_session(self, client_wrapper):
        self.client_wrapper = client_wrapper

    def set_groups(self, groups: list[str]):
        if groups != self.groups:
            self.monitored_chat_ids.clear()
            self.discussion_chat_ids.clear()
        self.groups = groups

    def update_config(self, send_to_saved: bool, target_group: str, hook_ids: list[int]):
        self.send_to_saved = send_to_saved
        self.target_group = target_group
        self.hook_ids = hook_ids

    def start(self):
        self.starting = False
        self.running = True
        self.received_count = 0

    def stop(self):
        self.running = False
        self.starting = False
        self.handler = None
        self.monitored_chat_ids.clear()
        self.discussion_chat_ids.clear()
