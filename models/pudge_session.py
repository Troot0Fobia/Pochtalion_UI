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
        self.monitored_chat_ids: set[int] = set()   # resolved numeric IDs (regular groups/supergroups)
        self.discussion_chat_ids: set[int] = set()  # linked discussion group IDs for channels
        self.broadcast_chat_ids: set[int] = set()   # broadcast channel IDs (for historical scan)
        self.received_count: int = 0
        self.saved_count: int = 0       # fallback-to-saved count for real-time
        self.scan_running: bool = False
        self.scan_task: Any = None
        self.scan_found: int = 0
        self.scan_processed: int = 0
        self.scan_total: int = 0
        self.scan_saved: int = 0        # fallback-to-saved count for historical scan

    def set_session(self, client_wrapper):
        self.client_wrapper = client_wrapper

    def set_groups(self, groups: list[str]):
        if groups != self.groups:
            self.monitored_chat_ids.clear()
            self.discussion_chat_ids.clear()
            self.broadcast_chat_ids.clear()
        self.groups = groups

    def update_config(self, send_to_saved: bool, target_group: str, hook_ids: list[int]):
        self.send_to_saved = send_to_saved
        self.target_group = target_group
        self.hook_ids = hook_ids

    def start(self):
        self.starting = False
        self.running = True
        self.received_count = 0
        self.saved_count = 0

    def stop(self):
        self.running = False
        self.starting = False
        self.handler = None
        self.monitored_chat_ids.clear()
        self.discussion_chat_ids.clear()
        self.broadcast_chat_ids.clear()

    def stop_scan(self):
        self.scan_running = False
        if self.scan_task and not self.scan_task.done():
            self.scan_task.cancel()
        self.scan_task = None
