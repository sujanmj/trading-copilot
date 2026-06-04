#!/usr/bin/env python3
"""Unit tests for watchdog alert throttle (Stage 46H)."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytz

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

IST = pytz.timezone('Asia/Kolkata')


def _fail(msg: str) -> int:
    print(f'WATCHDOG_ALERT_THROTTLE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _ist(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return IST.localize(datetime(y, m, d, hh, mm, 0))


def main() -> int:
    from backend.orchestration.watchdog_throttle import (
        STATE_FILE,
        THROTTLE_WINDOW_SEC,
        can_send_emergency_telegram,
        can_send_stale_telegram,
        emergency_telegram_allowed,
        format_stale_watchdog_message,
        record_emergency_telegram_sent,
        record_stale_telegram_sent,
    )
    from backend.storage.json_io import atomic_write_json

    if THROTTLE_WINDOW_SEC != 90 * 60:
        return _fail('throttle window must be 90 minutes')

    atomic_write_json(STATE_FILE, {})
    if not can_send_stale_telegram():
        return _fail('first stale alert should be allowed')
    record_stale_telegram_sent()
    if can_send_stale_telegram():
        return _fail('max 1 stale alert per 90 minutes')

    atomic_write_json(STATE_FILE, {})
    with patch('backend.orchestration.watchdog_throttle.emergency_telegram_allowed', return_value=True):
        if not can_send_emergency_telegram():
            return _fail('first emergency alert should be allowed during session')
        record_emergency_telegram_sent()
        if can_send_emergency_telegram():
            return _fail('max 1 emergency alert per 90 minutes')

    atomic_write_json(STATE_FILE, {})
    with patch('backend.orchestration.watchdog_throttle.is_recovery_in_progress', return_value=True):
        if can_send_stale_telegram():
            return _fail('no stale spam when recovery in progress')
        if can_send_emergency_telegram():
            return _fail('no emergency spam when recovery in progress')

    atomic_write_json(STATE_FILE, {})
    after_close = _ist(2026, 6, 2, 17, 0)
    if emergency_telegram_allowed(after_close):
        return _fail('emergency should be suppressed after India market close')
    with patch('backend.orchestration.watchdog_throttle.emergency_telegram_allowed', return_value=False):
        if can_send_emergency_telegram():
            return _fail('no repeated emergency after market close')

    market_open = _ist(2026, 6, 2, 10, 0)
    if not emergency_telegram_allowed(market_open):
        return _fail('emergency allowed during market hours')

    msg = format_stale_watchdog_message(7200, 'MARKET_HOURS')
    if 'anthropic' in msg.lower() or 'claude' in msg.lower():
        return _fail('watchdog message must not name providers')
    if len(msg) > 400:
        return _fail('watchdog message should be concise')

    routing = (PROJECT_ROOT / 'backend/utils/alert_routing.py').read_text(encoding='utf-8')
    if 'watchdog_throttle' not in routing:
        return _fail('alert_routing not wired to watchdog_throttle')

    atomic_write_json(STATE_FILE, {'last_stale_telegram_at': time.time() - THROTTLE_WINDOW_SEC - 5})
    with patch('backend.orchestration.watchdog_throttle.is_recovery_in_progress', return_value=False):
        if not can_send_stale_telegram():
            return _fail('stale should be allowed after 90min window elapses')

    print('WATCHDOG_ALERT_THROTTLE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
