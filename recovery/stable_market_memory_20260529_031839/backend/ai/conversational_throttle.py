"""
Telegram conversational throttling — per-user cooldown, burst protection, duplicate suppression.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, Optional

from backend.ai.conversational_cache import get_cached, normalize_question

DUPLICATE_SEC = 30
BURST_LIMIT = 10
BURST_WINDOW_SEC = 60
BURST_COOLDOWN_SEC = 120
COMMAND_COOLDOWN_SEC = 15

_lock = threading.Lock()
_user_timestamps: Dict[str, deque] = defaultdict(lambda: deque(maxlen=64))
_user_last_question: Dict[str, Dict[str, Any]] = {}
_user_cooldown_until: Dict[str, float] = {}
_user_last_command: Dict[str, Dict[str, Any]] = {}


def _now() -> float:
    return time.time()


def check_telegram_ask(user_id: str, question: str) -> dict:
    """
    Returns:
        allowed: bool
        reason: str (when blocked)
        cached_response: optional cached AI result dict
        suppress: bool — True when silently suppress (duplicate)
    """
    uid = (user_id or 'unknown').strip() or 'unknown'
    norm = normalize_question(question)
    now = _now()

    with _lock:
        cooldown_until = float(_user_cooldown_until.get(uid) or 0)
        if now < cooldown_until:
            remaining = int(cooldown_until - now)
            return {
                'allowed': False,
                'reason': f'Cooldown active — wait {remaining}s before another /ask.',
                'cached_response': None,
                'suppress': False,
            }

        last = _user_last_question.get(uid)
        if last and last.get('norm') == norm and (now - float(last.get('ts', 0))) < DUPLICATE_SEC:
            cached = get_cached('telegram_ask', question)
            return {
                'allowed': False,
                'reason': 'Duplicate question within 30s — suppressed.',
                'cached_response': cached,
                'suppress': True,
            }

        dq = _user_timestamps[uid]
        while dq and (now - dq[0]) > BURST_WINDOW_SEC:
            dq.popleft()
        if len(dq) >= BURST_LIMIT:
            _user_cooldown_until[uid] = now + BURST_COOLDOWN_SEC
            try:
                from backend.analytics.provider_analytics import record_throttle_block
                record_throttle_block('burst')
            except Exception:
                pass
            return {
                'allowed': False,
                'reason': f'Rate limit — max {BURST_LIMIT} asks/minute. Cooldown {BURST_COOLDOWN_SEC}s.',
                'cached_response': None,
                'suppress': False,
            }

        cached = get_cached('telegram_ask', question)
        if cached:
            _user_last_question[uid] = {'norm': norm, 'ts': now}
            return {
                'allowed': True,
                'reason': 'cache_hit',
                'cached_response': cached,
                'suppress': False,
            }

        dq.append(now)
        _user_last_question[uid] = {'norm': norm, 'ts': now}

    return {
        'allowed': True,
        'reason': 'ok',
        'cached_response': None,
        'suppress': False,
    }


def check_repeated_command(user_id: str, command: str) -> Optional[str]:
    """Suppress identical commands within COMMAND_COOLDOWN_SEC."""
    uid = (user_id or 'unknown').strip() or 'unknown'
    cmd = (command or '').strip().lower()
    now = _now()
    with _lock:
        last = _user_last_command.get(uid)
        if last and last.get('cmd') == cmd and (now - float(last.get('ts', 0))) < COMMAND_COOLDOWN_SEC:
            return f'Command /{cmd} already sent — wait {COMMAND_COOLDOWN_SEC}s.'
        _user_last_command[uid] = {'cmd': cmd, 'ts': now}
    return None
