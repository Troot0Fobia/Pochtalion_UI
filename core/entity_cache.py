import json

from telethon.tl import types
from telethon.tl.types import InputPeerChannel, InputPeerChat

from core.paths import SESSIONS

_CACHE_FILE = SESSIONS / "entity_cache.json"

# Module-level singleton — loaded once per process, never re-read from disk.
# Since asyncio is single-threaded, all writes are atomic (no await between
# dict mutation and disk flush), so no locking is needed.
_cache: dict | None = None


def _get_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    loaded: dict = {}
    if _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except Exception:
            pass
    _cache = loaded
    return _cache


def _flush() -> None:
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)


def load_session_entities(session_file: str) -> dict[str, InputPeerChannel | InputPeerChat]:
    result = {}
    for group_key, entry in _get_cache().get(session_file, {}).items():
        try:
            t = entry.get("type")
            if t == "channel":
                result[group_key] = InputPeerChannel(entry["id"], entry["access_hash"])
            elif t == "chat":
                result[group_key] = InputPeerChat(entry["id"])
        except (KeyError, TypeError):
            pass
    return result


def save_entity(session_file: str, group_key: str, entity) -> None:
    if isinstance(entity, types.Channel):
        entry = {"type": "channel", "id": entity.id, "access_hash": entity.access_hash}
    elif isinstance(entity, types.Chat):
        entry = {"type": "chat", "id": entity.id}
    else:
        return

    cache = _get_cache()
    cache.setdefault(session_file, {})[group_key] = entry
    _flush()
