#!/usr/bin/env python3
"""Unit tests for watchdog throttle (Stage 46H)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'WATCHDOG_THROTTLE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.orchestration.watchdog_throttle import (
        STATE_FILE,
        can_send_emergency_telegram,
        can_send_stale_telegram,
        format_stale_watchdog_message,
        record_stale_telegram_sent,
    )
    from backend.storage.json_io import atomic_write_json

    atomic_write_json(STATE_FILE, {'last_stale_telegram_at': time.time()})
    if can_send_stale_telegram():
        return _fail('second stale within 90min should throttle')
    atomic_write_json(STATE_FILE, {})

    msg = format_stale_watchdog_message(7200, 'MARKET_HOURS')
    if 'anthropic' in msg.lower() or 'claude' in msg.lower():
        return _fail('watchdog message must not name providers')
    if len(msg) > 400:
        return _fail('watchdog message should be concise')

    routing = (PROJECT_ROOT / 'backend/utils/alert_routing.py').read_text(encoding='utf-8')
    if 'watchdog_throttle' not in routing:
        return _fail('alert_routing not wired to watchdog_throttle')

    record_stale_telegram_sent()
    if can_send_stale_telegram():
        return _fail('should throttle after record')

    print('WATCHDOG_THROTTLE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
