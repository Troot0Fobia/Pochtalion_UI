from asyncio import Task


class GroupMail:

    def __init__(self, session_file: str):
        self.session_file: str = session_file
        self.client_wrapper = None
        self.task: Task | None = None
        self.running: bool = False
        self.delay: int = 0
        self.groups: list[str] = []
        self.sended_count: int = 0

    def set_session(self, client_wrapper):
        self.client_wrapper = client_wrapper

    def set_task(self, task: Task):
        self.task = task

    def set_delay(self, delay: int):
        self.delay = delay

    def set_groups(self, groups: list[str]):
        self.groups = groups

    def start(self):
        self.running = True
        self.sended_count = 0

    def stop(self):
        self.running = False

        if self.task:
            self.task.cancel()
            self.task = None

    def __str__(self):
        return (
            f"Session file: {self.session_file}\n"
            f"client wrapper: {self.client_wrapper}\n"
            f"task: {self.task}\n"
            f"running: {self.running}\n"
            f"delay: {self.delay}\n"
            f"group: {self.groups}"
        )
