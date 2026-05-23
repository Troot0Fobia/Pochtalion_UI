import asyncio
import base64
import random
import re
import time

from telethon.errors import (
    ChannelPrivateError,
    ChatWriteForbiddenError,
    FloodWaitError,
    ForbiddenError,
    InputUserDeactivatedError,
    InviteRequestSentError,
    PeerFloodError,
    SlowModeWaitError,
    UserBannedInChannelError,
)

from core.logger import setup_logger
from core.paths import SMM_IMAGES
from models.group_mail import GroupMail


_RETRY_DELAYS = (30, 60, 90, 120)  # seconds; total 5 attempts, ~5 min max wait
_MAX_RETRIES = len(_RETRY_DELAYS) + 1

# Patterns for group identifier normalisation
_INVITE_RE = re.compile(r"^(?:https?://)?t\.me/(?:joinchat/|\+)[a-zA-Z0-9_=\-]+$")
_ADDLIST_RE = re.compile(r"^(?:https?://)?t\.me/addlist/", re.IGNORECASE)
_TGME_USERNAME_RE = re.compile(r"^(?:https?://)?t\.me/([a-zA-Z][a-zA-Z0-9_]{2,})$", re.IGNORECASE)


def _normalize_group(raw: str) -> str:
    """Return a canonical identifier for a group/channel string.

    Numeric IDs, invite links, and folder links pass through unchanged.
    Public t.me/username URLs and bare usernames are collapsed to @username.
    """
    s = raw.strip()
    if not s:
        return s
    if s.startswith("-"):            # numeric peer ID
        return s
    if _INVITE_RE.match(s):          # joinchat / + private invite
        return s
    if _ADDLIST_RE.match(s):         # t.me/addlist/ folder link
        return s
    m = _TGME_USERNAME_RE.match(s)
    if m:                            # https://t.me/username or t.me/username
        return f"@{m.group(1).lower()}"
    return f"@{s.lstrip('@').lower()}"  # @Username or bare username


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

        if group_mail.running:
            self.main_window.show_notification(
                "Внимание", "Нельзя изменять список групп во время рассылки"
            )
            return

        seen: set[str] = set()
        groups: list[str] = []
        for raw in groups_str.splitlines():
            normalized = _normalize_group(raw)
            if normalized and normalized not in seen:
                seen.add(normalized)
                groups.append(normalized)
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

        if group_mail.running or group_mail.starting:
            return True

        group_mail.starting = True
        try:
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
            await self._resolve_folder_links(session_id, group_mail, session)
            group_mail.set_delay(int(delay) if delay else 0)
            group_mail.set_task(asyncio.create_task(self.group_mail(session_id)))
            group_mail.start()
            return True
        finally:
            group_mail.starting = False

    async def _resolve_folder_links(self, session_id: str, group_mail, session) -> None:
        resolved: list[str] = []
        folder_count = 0
        for line in group_mail.groups:
            if session._ADDLIST_RE.match(line.strip()):
                folder_count += 1
                groups_from_folder = await session.resolve_chat_folder(line)
                resolved.extend(groups_from_folder)
            else:
                resolved.append(line)
        if folder_count:
            group_mail.set_resolved_groups(resolved)
            self.logger.info(
                f"[{session_id}] Resolved {folder_count} folder link(s) → {len(resolved)} groups total"
            )

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
            groups = group_mail.resolved_groups if group_mail.resolved_groups is not None else group_mail.groups
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

            if group in group_mail.pending_approval:
                if await session.is_joined(session._client, group):
                    group_mail.pending_approval.discard(group)
                else:
                    group_mail.group_index = (group_mail.group_index + 1) % len(groups)
                    continue

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
            except InviteRequestSentError:
                self.logger.info(f"Join request sent for group {group}, waiting for approval")
                group_mail.pending_approval.add(group)
                self.main_window.show_notification(
                    "Внимание",
                    f"Отправлена заявка на вступление в группу {group} — ожидаем одобрения",
                )
            except InputUserDeactivatedError as e:
                self.logger.error(
                    f"Catched User Deactivated Error, skip group {group}",
                    exc_info=e,
                )
            except (ChannelPrivateError, ChatWriteForbiddenError, UserBannedInChannelError) as e:
                self.logger.warning(
                    f"Banned or write-restricted in group {group}, removing from list",
                    exc_info=e,
                )
                if group_mail.resolved_groups is not None:
                    group_mail.resolved_groups = [g for g in group_mail.resolved_groups if g != group]
                else:
                    group_mail.groups = [g for g in group_mail.groups if g != group]
                await session.leaveGroup(group)
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
                self.logger.error("Session disconnected, attempting reconnect", exc_info=e)
                reconnected = await self._retry_on_disconnect(session_id, group_mail, session)
                if reconnected:
                    self.main_window.settings_bridge.updateGroupMailingRetry.emit(
                        session_id, 0, 0, 0
                    )
                else:
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

    async def _retry_on_disconnect(self, session_id: str, group_mail, session) -> bool:
        for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
            self.logger.info(
                f"Reconnect attempt {attempt}/{_MAX_RETRIES}, waiting {delay}s"
            )
            self.main_window.settings_bridge.updateGroupMailingRetry.emit(
                session_id, attempt, _MAX_RETRIES, delay
            )
            await asyncio.sleep(delay)
            if not group_mail.running:
                return False
            if await session.reconnect():
                self.logger.info(f"Reconnected on attempt {attempt}/{_MAX_RETRIES}")
                return True
        self.logger.error("All reconnect attempts exhausted")
        return False

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
