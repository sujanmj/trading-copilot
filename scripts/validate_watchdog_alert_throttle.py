#!/usr/bin/env python3
"""Validate watchdog alert throttle pack (Stage 46H)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'WATCHDOG_ALERT_THROTTLE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    path = PROJECT_ROOT / 'backend/orchestration/watchdog_throttle.py'
    if not path.is_file():
        return _fail('missing watchdog_throttle.py')

    src = path.read_text(encoding='utf-8')
    for needle in (
        'THROTTLE_WINDOW_SEC',
        'can_send_stale_telegram',
        'can_send_emergency_telegram',
        'is_recovery_in_progress',
        'emergency_telegram_allowed',
    ):
        if needle not in src:
            return _fail(f'missing {needle} in watchdog_throttle.py')

    if os.system(f'{sys.executable} scripts/test_watchdog_alert_throttle.py') != 0:
        return _fail('test_watchdog_alert_throttle.py failed')

    print('WATCHDOG_ALERT_THROTTLE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
