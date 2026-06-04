"""
Watchdog Telegram throttle (Stage 46H).

Max 1 stale + 1 emergency alert per 90 minutes; no repeat during recovery.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
STATE_FILE = get_data_path('watchdog_throttle_state.json')
THROTTLE_WINDOW_SEC = 90 * 60


def _log(tag: str, msg: str) -> None:
    print(f'[{tag}] {msg}', flush=True)


def _load_state() -> dict:
    if not STATE_FILE.is_file():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    atomic_write_json(STATE_FILE, state)


def _within_window(last_ts: float) -> bool:
    if not last_ts:
        return False
    return (time.time() - float(last_ts)) < THROTTLE_WINDOW_SEC


def is_recovery_in_progress() -> bool:
    try:
        from backend.api import api_server as api_mod
        if getattr(api_mod, '_analyzer_running', False):
            return True
        if getattr(api_mod, '_watchdog_refresh_pending', False):
            return True
    except Exception:
        pass
    try:
        from backend.utils.process_lock import lock_status
        if lock_status().get('master_analyzer', {}).get('alive'):
            return True
    except Exception:
        pass
    return False


def emergency_telegram_allowed(now: Optional[datetime] = None) -> bool:
    """No emergency Telegram after India close (post-market / after-hours / night)."""
    from backend.utils.market_hours import get_market_period
    period = get_market_period(now)
    return period in ('market', 'pre_market', 'preopen')


def can_send_stale_telegram() -> bool:
    if is_recovery_in_progress():
        _log('WATCHDOG_THROTTLE', 'stale suppressed — recovery in progress')
        return False
    state = _load_state()
    if _within_window(float(state.get('last_stale_telegram_at') or 0)):
        _log('WATCHDOG_THROTTLE', 'stale suppressed — 90min window')
        return False
    return True


def can_send_emergency_telegram() -> bool:
    if not emergency_telegram_allowed():
        _log('WATCHDOG_THROTTLE', 'emergency suppressed — session closed')
        return False
    if is_recovery_in_progress():
        _log('WATCHDOG_THROTTLE', 'emergency suppressed — recovery in progress')
        return False
    state = _load_state()
    if _within_window(float(state.get('last_emergency_telegram_at') or 0)):
        _log('WATCHDOG_THROTTLE', 'emergency suppressed — 90min window')
        return False
    return True


def record_stale_telegram_sent() -> None:
    state = _load_state()
    state['last_stale_telegram_at'] = time.time()
    _save_state(state)


def record_emergency_telegram_sent() -> None:
    state = _load_state()
    state['last_emergency_telegram_at'] = time.time()
    _save_state(state)


def format_stale_watchdog_message(age_seconds: int, mode: str) -> str:
    hours = max(1, age_seconds // 3600)
    return (
        f'<b>⚠ Data stale</b>\n'
        f'Intelligence ~{hours}h old ({mode}). Auto-refresh running.\n'
        f'<i>Watch only until feeds recover.</i>'
    )
