"""
Pending /feed input state per Telegram chat (Stage 50B final).
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

FEED_PENDING_TTL_SECONDS = 120

_lock = Lock()
_pending_until: dict[str, float] = {}


def chat_key_from_message(message: dict[str, Any]) -> str:
    chat = message.get('chat') or {}
    return str(chat.get('id') or 'default')


def set_feed_pending(chat_id: str, *, ttl_seconds: int = FEED_PENDING_TTL_SECONDS) -> None:
    key = str(chat_id or 'default')
    with _lock:
        _pending_until[key] = time.time() + max(1, int(ttl_seconds))


def clear_feed_pending(chat_id: str) -> None:
    key = str(chat_id or 'default')
    with _lock:
        _pending_until.pop(key, None)


def is_feed_pending(chat_id: str) -> bool:
    key = str(chat_id or 'default')
    with _lock:
        expires = _pending_until.get(key)
        if not expires:
            return False
        if time.time() > expires:
            _pending_until.pop(key, None)
            return False
        return True


def reset_feed_pending_state() -> None:
    with _lock:
        _pending_until.clear()
