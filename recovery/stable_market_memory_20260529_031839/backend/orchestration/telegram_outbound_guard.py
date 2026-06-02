"""
Telegram outbound dedupe — prevents duplicate sends, separates loading vs final.

Hash key: normalized(message) + command + cycle_id
Loading messages for the same command reuse/edit within cooldown instead of resending.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple

COOLDOWN_SECONDS = float(os.environ.get('TELEGRAM_OUTBOUND_COOLDOWN_SEC', '45'))
HANDLER_ID = f"tg-{os.getpid()}"

_lock = threading.Lock()
_recent_hashes: Dict[str, float] = {}
_loading: Dict[str, Dict[str, Any]] = {}
_active_cycles: Dict[str, str] = {}


def _normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').strip())


def outbound_hash(message: str, command: str = '', cycle_id: str = '') -> str:
    raw = f"{_normalize(message)}|{command}|{cycle_id}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


def new_cycle_id(command: str) -> str:
    return f"{command}-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def bind_cycle(command: str, cycle_id: str) -> None:
    with _lock:
        _active_cycles[command] = cycle_id


def get_cycle_id(command: str) -> str:
    with _lock:
        return _active_cycles.get(command) or ''


def trace_emit(
    source_command: str,
    message_kind: str,
    msg_hash: str,
    *,
    cycle_id: str = '',
    skipped: bool = False,
    reason: str = '',
) -> None:
    status = 'SKIP' if skipped else 'SEND'
    suffix = f" reason={reason}" if reason else ''
    try:
        from backend.utils.telegram_bot import safe_print
    except Exception:
        def safe_print(t):
            print(t)
    safe_print(
        f"[TG EMIT {status}] cmd={source_command or '-'} kind={message_kind} "
        f"handler={HANDLER_ID} cycle={cycle_id or '-'} hash={msg_hash[:12]}{suffix}"
    )


def should_send_outbound(
    message: str,
    *,
    command: str = '',
    cycle_id: str = '',
    message_kind: str = 'final',
) -> Tuple[bool, Optional[str], str, Optional[int]]:
    """
    Returns (allowed, skip_reason, msg_hash, existing_loading_message_id).
    """
    kind = (message_kind or 'final').lower()
    hash_cycle = cycle_id if kind != 'loading' else f"{cycle_id}:loading"
    msg_hash = outbound_hash(message, command, hash_cycle)
    now = time.time()

    with _lock:
        if kind == 'loading' and command:
            prev = _loading.get(command)
            if prev:
                same_text = prev.get('text') == _normalize(message)
                within = (now - float(prev.get('at') or 0)) < COOLDOWN_SECONDS
                if same_text and within:
                    return False, 'loading_duplicate', msg_hash, prev.get('message_id')
                if within and prev.get('message_id'):
                    return True, 'loading_update', msg_hash, prev.get('message_id')

        last = _recent_hashes.get(msg_hash)
        if last and (now - last) < COOLDOWN_SECONDS:
            return False, 'cooldown', msg_hash, None

    return True, None, msg_hash, None


def record_outbound(
    msg_hash: str,
    *,
    command: str = '',
    message_kind: str = 'final',
    message_id: Optional[int] = None,
    text: str = '',
) -> None:
    now = time.time()
    with _lock:
        _recent_hashes[msg_hash] = now
        cutoff = now - COOLDOWN_SECONDS * 4
        for key, ts in list(_recent_hashes.items()):
            if ts < cutoff:
                _recent_hashes.pop(key, None)
        if (message_kind or '').lower() == 'loading' and command:
            _loading[command] = {
                'message_id': message_id,
                'text': _normalize(text),
                'at': now,
            }


def clear_loading(command: str) -> None:
    with _lock:
        _loading.pop(command, None)


def prepare_send(
    text: str,
    *,
    command: str = '',
    cycle_id: str = '',
    message_kind: str = 'final',
) -> Dict[str, Any]:
    allowed, reason, msg_hash, edit_id = should_send_outbound(
        text,
        command=command,
        cycle_id=cycle_id,
        message_kind=message_kind,
    )
    if not allowed:
        trace_emit(command, message_kind, msg_hash, cycle_id=cycle_id, skipped=True, reason=reason or 'blocked')
        return {'action': 'skip', 'reason': reason, 'msg_hash': msg_hash}

    if reason == 'loading_update' and edit_id:
        trace_emit(command, message_kind, msg_hash, cycle_id=cycle_id)
        return {
            'action': 'edit',
            'message_id': edit_id,
            'msg_hash': msg_hash,
        }

    trace_emit(command, message_kind, msg_hash, cycle_id=cycle_id)
    return {'action': 'send', 'msg_hash': msg_hash}
