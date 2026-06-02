"""
Telegram command debounce + in-flight guard — prevents duplicate status messages.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Callable, Optional, Tuple, TypeVar

DEBOUNCE_SECONDS = float(__import__('os').environ.get('TELEGRAM_CMD_DEBOUNCE_SEC', '10'))

_lock = threading.Lock()
_handler_mutex = threading.Lock()
_inflight: dict = {}
_last_seen: dict = {}

T = TypeVar('T')

DUPLICATE_MESSAGE = '⏳ Command already processing...'


def _command_key(cmd: str, args: str = '', user_id: str = 'default') -> str:
    window = int(time.time() // max(1, int(DEBOUNCE_SECONDS)))
    raw = f"{user_id}|{cmd}|{(args or '').strip()[:80]}|{window}"
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


def duplicate_command_message(reason: Optional[str] = None, *, command: str = '') -> str:
    try:
        from backend.telegram.formatting.telegram_formatter import confirmation_phrase
        if reason == 'in_flight':
            return confirmation_phrase('in_flight', command=command)
    except Exception:
        pass
    if reason == 'debounce':
        return DUPLICATE_MESSAGE
    return DUPLICATE_MESSAGE


def run_guarded(
    cmd: str,
    fn: Callable[[], T],
    *,
    args: str = '',
    user_id: str = 'default',
    on_skip: Optional[Callable[[Optional[str]], None]] = None,
) -> Optional[T]:
    """Execute fn under command guard + handler mutex."""
    skip, reason, key = begin_command(cmd, args, user_id)
    if skip:
        if on_skip:
            on_skip(reason)
        return None
    with _handler_mutex:
        try:
            return fn()
        finally:
            finish_command(key)


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
