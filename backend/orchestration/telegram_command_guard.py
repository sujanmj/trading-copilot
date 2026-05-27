"""
Telegram command debounce + in-flight guard — prevents duplicate status messages.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Optional, Tuple

DEBOUNCE_SECONDS = float(__import__('os').environ.get('TELEGRAM_CMD_DEBOUNCE_SEC', '3'))

_lock = threading.Lock()
_inflight: dict = {}
_last_seen: dict = {}


def _command_key(cmd: str, args: str = '', user_id: str = 'default') -> str:
    raw = f"{user_id}|{cmd}|{(args or '').strip()[:80]}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def begin_command(cmd: str, args: str = '', user_id: str = 'default') -> Tuple[bool, Optional[str], str]:
    """
    Returns (should_skip, reason, key).
    Call finish_command(key) when background work completes.
    """
    key = _command_key(cmd, args, user_id)
    now = time.time()
    with _lock:
        if key in _inflight:
            return True, 'in_flight', key
        last = _last_seen.get(key)
        if last and (now - last) < DEBOUNCE_SECONDS:
            return True, 'debounce', key
        _inflight[key] = now
        _last_seen[key] = now
    return False, None, key


def finish_command(key: str) -> None:
    with _lock:
        _inflight.pop(key, None)


def guarded_command(cmd: str, args: str = '', user_id: str = 'default'):
    """Decorator-friendly context for synchronous handlers."""

    class _Guard:
        def __init__(self):
            self.skip = False
            self.reason = None
            self.key = ''

        def __enter__(self):
            self.skip, self.reason, self.key = begin_command(cmd, args, user_id)
            return self

        def __exit__(self, exc_type, exc, tb):
            finish_command(self.key)
            return False

    return _Guard()
