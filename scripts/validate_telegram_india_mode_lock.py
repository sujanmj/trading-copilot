#!/usr/bin/env python3
"""Validate Telegram India mode lock (Stage 48K)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    lock_src = (PROJECT_ROOT / 'backend/telegram/india_mode_lock.py').read_text(encoding='utf-8')
    fmt_src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    for needle in ('resolve_telegram_market_mode', 'TELEGRAM_ALLOW_USA_MODE', 'INDIA_MODE'):
        if needle not in lock_src:
            print(f'TELEGRAM_INDIA_MODE_LOCK_FAIL: india_mode_lock missing {needle}', file=sys.stderr)
            return 1
    if 'resolve_telegram_market_mode' not in fmt_src:
        print('TELEGRAM_INDIA_MODE_LOCK_FAIL: response_format missing mode lock', file=sys.stderr)
        return 1
    if os.system(f'{sys.executable} scripts/test_telegram_india_mode_lock.py') != 0:
        print('TELEGRAM_INDIA_MODE_LOCK_FAIL: test failed', file=sys.stderr)
        return 1
    print('TELEGRAM_INDIA_MODE_LOCK_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
