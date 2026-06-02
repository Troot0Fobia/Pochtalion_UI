import re

from telethon import events, types, utils
from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest

from core.logger import setup_logger
from models.pudge_session import PudgeSession


_INVITE_RE = re.compile(r"^(?:https?://)?t\.me/(?:joinchat/|\+)[a-zA-Z0-9_=\-]+$")
_ADDLIST_RE = re.compile(r"^(?:https?://)?t\.me/addlist/", re.IGNORECASE)
_TGME_USERNAME_RE = re.compile(r"^(?:https?://)?t\.me/([a-zA-Z][a-zA-Z0-9_]{2,})$", re.IGNORECASE)


def _hook_matches_words(hook: str, text: str) -> bool:
    words = hook.lower().split()
    if not words:
        return False
    pattern = r"\s+".join(r"(?<!\w)" + re.escape(w) + r"(?!\w)" for w in words)
    return bool(re.search(pattern, text))


def _normalize_group(raw: str) -> str:
    s = raw.strip()
    if not s:
        return s
    if s.startswith("-"):
        return s
    if _INVITE_RE.match(s):
        return s
    if _ADDLIST_RE.match(s):
        return s
    m = _TGME_USERNAME_RE.match(s)
    if m:
        return f"@{m.group(1).lower()}"
    return f"@{s.lstrip('@').lower()}"


class PudgeManager:

    def __init__(self, main_window) -> None:
        self.main_window = main_window
        self.work_sessions: dict[str, PudgeSession] = {}
        self.logger = setup_logger("Pochtalion.PudgeManager", "pudge_manager.log")

    def add_session(self, session_id: str, session_file: str):
        self.work_sessions[session_id] = PudgeSession(session_file)

    def update_groups(self, session_id: str, groups_str: str):
        session = self.work_sessions.get(session_id)
        if session is None:
            return
        if session.running:
            self.main_window.show_notification("Внимание", "Нельзя изменять список групп во время мониторинга")
            return
        seen: set[str] = set()
        groups: list[str] = []
        for raw in groups_str.splitlines():
            normalized = _normalize_group(raw)
            if normalized and normalized not in seen:
                seen.add(normalized)
                groups.append(normalized)
        session.set_groups(groups)

    def get_session_groups(self, session_id: str) -> str:
        session = self.work_sessions.get(session_id)
        if session is None:
            return ""
        return "\n".join(session.groups)

    def update_config(self, session_id: str, send_to_saved: bool, target_group: str, hook_ids: list[int]):
        session = self.work_sessions.get(session_id)
        if session is None:
            return
        session.update_config(send_to_saved, target_group, hook_ids)

    def is_session_running(self, session_id: str) -> bool:
        session = self.work_sessions.get(session_id)
        return session.running if session else False

    async def start_pudge(self, session_id: str) -> bool:
        session = self.work_sessions.get(session_id)
        if session is None:
            self.logger.error("Session %s not found in work_sessions", session_id)
            return False

        if session.running or session.starting:
            return True

        session.starting = True
        try:
            if not session.groups:
                self.main_window.show_notification("Внимание", "Нет групп для мониторинга")
                return False

            if not session.hook_ids:
                self.main_window.show_notification("Внимание", "Не выбраны хуки для мониторинга")
                return False

            if not session.send_to_saved and not session.target_group.strip():
                self.main_window.show_notification("Внимание", "Укажите группу для отправки уведомлений")
                return False

            wrapper = await self.main_window.session_manager.get_or_start_session(
                int(session_id), session.session_file
            )
            if wrapper is None:
                self.logger.error("Failed to start session %s for pudge", session_id)
                return False

            session.set_session(wrapper)
            await self._resolve_entities(session_id, session, wrapper)

            hook_messages = await self.main_window.database.get_hook_messages()
            hook_texts = [m["text"] for m in hook_messages if m["id"] in session.hook_ids]
            if not hook_texts:
                self.main_window.show_notification("Внимание", "Выбранные хуки не найдены в базе данных")
                return False

            handler = self._make_handler(session_id, session, wrapper, hook_texts)
            wrapper._client.add_event_handler(handler, events.NewMessage)
            session.handler = handler
            session.start()
            self.logger.info(
                "[%s] Pudge started: groups=%d, hooks=%d, target=%s",
                session_id,
                len(session.groups),
                len(hook_texts),
                "saved" if session.send_to_saved else session.target_group,
            )
            return True
        finally:
            session.starting = False

    async def _resolve_entities(self, session_id: str, session: PudgeSession, wrapper) -> None:
        monitored: set[int] = set()
        discussion: set[int] = set()

        for group in session.groups:
            try:
                entity = await wrapper._client.get_entity(group)

                is_broadcast_channel = (
                    isinstance(entity, types.Channel)
                    and getattr(entity, "broadcast", False)
                    and not getattr(entity, "megagroup", False)
                )

                if is_broadcast_channel:
                    # Subscribe to the channel if not already
                    if not await wrapper.is_joined(wrapper._client, group):
                        await wrapper._client(JoinChannelRequest(entity))

                    # Find the linked discussion group
                    full = await wrapper._client(GetFullChannelRequest(entity))
                    linked_id = full.full_chat.linked_chat_id
                    if linked_id:
                        # discussion group is a supergroup → marked peer_id = -(10^12 + id)
                        discussion.add(-(1_000_000_000_000 + linked_id))
                        self.logger.info(
                            "[%s] Channel %s → discussion group %d", session_id, group, linked_id
                        )
                    else:
                        self.logger.warning("[%s] Channel %s has no linked discussion group", session_id, group)
                else:
                    # Regular group or supergroup: join if needed
                    if not await wrapper.is_joined(wrapper._client, group):
                        await wrapper._client(JoinChannelRequest(entity))
                    # utils.get_peer_id returns the same marked ID that event.chat_id uses
                    monitored.add(utils.get_peer_id(entity))

            except Exception as e:
                self.logger.warning("[%s] Failed to resolve group '%s': %s", session_id, group, e)

        session.monitored_chat_ids = monitored
        session.discussion_chat_ids = discussion

    def _make_handler(self, session_id: str, session: PudgeSession, wrapper, hook_texts: list[str]):
        async def handler(event):
            if not session.running:
                return

            chat_id = event.chat_id
            is_discussion = chat_id in session.discussion_chat_ids
            is_monitored = chat_id in session.monitored_chat_ids

            if not is_discussion and not is_monitored:
                return

            # For discussion groups only process replies (actual comments to channel posts)
            if is_discussion and not getattr(event.message, "reply_to", None):
                return

            if event.out:
                return

            text = (event.raw_text or "").lower()
            if not text:
                return

            if not any(_hook_matches_words(hook, text) for hook in hook_texts):
                return

            try:
                chat = await event.get_chat()
                username = getattr(chat, "username", None)
                if username:
                    link = f"https://t.me/{username}/{event.id}"
                else:
                    # chat.id is the raw positive channel/chat id — correct for t.me/c/ links
                    link = f"https://t.me/c/{chat.id}/{event.id}"

                target = "me" if session.send_to_saved else session.target_group.strip()
                await wrapper._client.send_message(target, link)

                session.received_count += 1
                self.main_window.settings_bridge.updatePudgeReceivedCount.emit(
                    session_id, session.received_count
                )
                self.logger.info("[%s] Hook matched in chat %d, link sent to %s", session_id, chat_id, target)
            except Exception as e:
                self.logger.error("[%s] Error sending hook notification: %s", session_id, e)

        return handler

    async def stop_pudge(self, session_id: str) -> None:
        session = self.work_sessions.get(session_id)
        if session is None:
            return
        if session.handler and session.client_wrapper:
            try:
                session.client_wrapper._client.remove_event_handler(session.handler)
            except Exception as e:
                self.logger.warning("[%s] Error removing event handler: %s", session_id, e)
        session.stop()
        self.logger.info("[%s] Pudge stopped", session_id)

    async def check_write_access(self, session_id: str, group: str) -> dict:
        session = self.work_sessions.get(session_id)
        if session is None:
            return {"ok": False, "error": "Сессия не найдена"}

        wrapper = await self.main_window.session_manager.get_or_start_session(
            int(session_id), session.session_file
        )
        if wrapper is None:
            return {"ok": False, "error": "Не удалось запустить сессию"}

        return await wrapper.check_write_access(group)

    async def stop_all(self) -> None:
        for session_id in list(self.work_sessions.keys()):
            await self.stop_pudge(session_id)
