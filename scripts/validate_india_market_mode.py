#!/usr/bin/env python3
"""Validate India market mode pack (Stage 46I)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'INDIA_MARKET_MODE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    router = PROJECT_ROOT / 'backend/analytics/market_calendar_router.py'
    if not router.is_file():
        return _fail('missing market_calendar_router.py')
    src = router.read_text(encoding='utf-8')
    for needle in ('get_india_telegram_mode', 'INDIA_MARKET_HOURS', 'INDIA_PREMARKET_MODE'):
        if needle not in src:
            return _fail(f'missing {needle}')

    status_src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    if 'get_india_telegram_mode' not in status_src:
        return _fail('response_format status missing get_india_telegram_mode')

    proc = os.system(f'{sys.executable} scripts/test_india_market_mode.py')
    if proc != 0:
        return _fail('test_india_market_mode.py failed')

    print('INDIA_MARKET_MODE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
