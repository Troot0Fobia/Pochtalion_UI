import asyncio
import base64
import random
import time

from telethon.errors import (
    FloodWaitError,
    ForbiddenError,
    InputUserDeactivatedError,
    PeerFloodError,
    SlowModeWaitError,
)

from core.logger import setup_logger
from core.paths import SMM_IMAGES
from models.group_mail import GroupMail


class GroupMailer:

    def __init__(self, main_window) -> None:
        self.main_window = main_window
        self.work_sessions: dict[str, GroupMail] = {}
        self.logger = setup_logger("Pochtalion.GroupMailer", "group_mailer.log")

    def add_session(self, session_id: str, session_file: str):
        self.work_sessions[session_id] = GroupMail(session_file)

    def update_groups(self, session_id: str, groups_str: str):
        group_mail = self.work_sessions.get(session_id)
        if group_mail is None:
            self.logger.error(
                f"Failed receive working session in update_groups with id {session_id}"
            )
            return

        groups = [g for g in groups_str.splitlines() if g.strip()]
        group_mail.set_groups(groups)

    def get_session_groups(self, session_id: str) -> str:
        group_mail = self.work_sessions.get(session_id)
        if group_mail is None:
            self.logger.error(
                f"Failed receive working session in get_groups with id {session_id}"
            )
            return ""

        return "\n".join(group_mail.groups)

    def is_session_mailing(self, session_id: str) -> bool:
        group_mail = self.work_sessions.get(session_id)
        if group_mail is None:
            return False

        return group_mail.running

    async def start_group_mailing(
        self,
        session_id: str,
        delay: int | str,
    ) -> bool:
        group_mail = self.work_sessions.get(session_id)
        if group_mail is None:
            self.logger.error(
                f"Failed receive working session in start_group_mailing with id {session_id}"
            )
            return False

        if group_mail.running:
            return True

        if not group_mail.groups:
            self.main_window.show_notification("Внимание", "Нет групп для отправки")
            return False

        session = await self.main_window.session_manager.get_or_start_session(
            int(session_id), group_mail.session_file
        )
        if session is None:
            self.logger.error(
                f"Failed start session for group mailing ({session_id}:{group_mail.session_file})"
            )
            return False

        group_mail.set_session(session)
        group_mail.set_delay(int(delay) if delay else 0)
        group_mail.set_task(asyncio.create_task(self.group_mail(session_id)))
        group_mail.start()
        return True

    async def group_mail(self, session_id: str):
        group_mail = self.work_sessions.get(session_id)

        if group_mail is None:
            self.logger.error(
                f"Failed receive working session in mailing with id {session_id}"
            )
            return

        session = group_mail.client_wrapper
        if session is None:
            return

        while group_mail.running:
            groups = group_mail.groups
            if not groups:
                self.main_window.show_notification(
                    "Внимание", "Нет групп для отправки"
                )
                group_mail.stop()
                break

            smm_msgs = await self.main_window.database.get_smm_messages()
            if not smm_msgs:
                self.main_window.show_notification(
                    "Внимание", "Нет сообщений для отправки"
                )
                group_mail.stop()
                break

            message = random.choice(smm_msgs)
            base64_file = None
            if message["photo"]:
                with open(SMM_IMAGES / message["photo"], "rb") as file:
                    base64_file = base64.b64encode(file.read()).decode("utf-8")

            message_to_send = {
                "base64_file": base64_file,
                "text": message["text"],
                "filename": message["photo"],
            }
            group = groups[group_mail.group_index % len(groups)]

            now = time.time()
            cooldown_until = group_mail.group_cooldowns.get(group, 0)
            if cooldown_until > now:
                soonest = min(group_mail.group_cooldowns.get(g, 0) for g in groups)
                if soonest > now:
                    self.logger.info(
                        f"All groups on slow mode cooldown, waiting {soonest - now:.0f}s"
                    )
                    await asyncio.sleep(soonest - now)
                group_mail.group_index = (group_mail.group_index + 1) % len(groups)
                continue

            try:
                send_time = await session.sendGroupMessage(group, message_to_send)
                if send_time is not None:
                    group_mail.sended_count += 1
                    self.main_window.settings_bridge.updateGroupMailingProgress.emit(
                        session_id, group_mail.sended_count, send_time
                    )
            except FloodWaitError as e:
                self.logger.error(
                    f"Catched Flood Wait Error, wait for {e.seconds}", exc_info=e
                )
                self.main_window.show_notification(
                    "Внимание",
                    f"Сессия {session.session_file} поймала флуд, ждем {e.seconds + 10} секунд",
                )
                await asyncio.sleep(e.seconds + 10)
            except PeerFloodError as e:
                self.logger.error(
                    f"Catched PeerFlood Error, stopping mailing for session {session.session_file}",
                    exc_info=e,
                )
                self.main_window.show_notification(
                    "Внимание",
                    f"Сессия {session.session_file} поймала флуд — рассылка остановлена",
                )
                group_mail.stop()
                break
            except InputUserDeactivatedError as e:
                self.logger.error(
                    f"Catched User Deactivated Error, skip group {group}",
                    exc_info=e,
                )
            except ForbiddenError as e:
                self.logger.error(
                    f"Catched Forbidden Error, skip group {group}",
                    exc_info=e,
                )
            except SlowModeWaitError as e:
                self.logger.warning(
                    f"Slow mode on group {group}, next send available in {e.seconds}s"
                )
                group_mail.group_cooldowns[group] = time.time() + e.seconds
            except ConnectionError as e:
                self.logger.error(
                    f"Session disconnected, stopping group mailing", exc_info=e
                )
                self.main_window.show_notification(
                    "Внимание",
                    f"Сессия {session.session_file} отключена — рассылка остановлена",
                )
                group_mail.stop()
                break
            except Exception as e:
                self.logger.error("Unexpected error during group mailing", exc_info=e)
            finally:
                group_mail.group_index = (group_mail.group_index + 1) % len(groups)

            if group_mail.running:
                await asyncio.sleep(group_mail.delay)

        # Loop exited due to internal stop (PeerFlood / no messages).
        # Task cancellation (external stop) raises CancelledError and never reaches here.
        self.main_window.settings_bridge.changeGroupMailingStatus.emit(session_id, False)

    async def stop_group_mailing(self, session_id: str) -> None:
        group_mail = self.work_sessions.get(session_id)

        if group_mail is None:
            self.logger.error(
                f"Failed receive working session in stopping with id {session_id}"
            )
            return

        group_mail.stop()

    async def stop_all(self) -> None:
        for group_mail in self.work_sessions.values():
            group_mail.stop()
