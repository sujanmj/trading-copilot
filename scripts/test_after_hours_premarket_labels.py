#!/usr/bin/env python3
"""Unit tests — after-hours premarket titles and rule text (Stage 48S)."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

IST = ZoneInfo('Asia/Kolkata')
AFTER_HOURS_MODE = {
    'market_mode': 'INDIA_AFTER_HOURS',
    'mode_code': 'INDIA_AFTER_HOURS_MODE',
}


def _fail(msg: str) -> int:
    print(f'AFTER_HOURS_PREMARKET_LABELS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.premarket_conviction import format_premarket_telegram

    premarket_data = {
        'market_bias': 'Neutral',
        'top_setups': [{'ticker': 'RELIANCE', 'score': 70, 'reasons': ['test'], 'setup': 'watch'}],
        'avoid': [],
        'market_mode': AFTER_HOURS_MODE,
        'freshness_ok': True,
        'generated_at': datetime.now(IST).isoformat(),
    }

    with patch('backend.analytics.market_calendar_router.get_india_telegram_mode', return_value=AFTER_HOURS_MODE):
        pre_text = format_premarket_telegram(full=False, report=premarket_data)
        if 'PREMARKET TOP SETUPS' in pre_text:
            return _fail('premarket title must not say PREMARKET during after-hours')
        if 'AFTER-HOURS WATCH' not in pre_text:
            return _fail('premarket missing AFTER-HOURS WATCH title')
        if 'Market open' in pre_text:
            return _fail('premarket must not say Market open during after-hours')
        if 'INDIA_AFTER_HOURS' not in pre_text:
            return _fail('premarket must show INDIA_AFTER_HOURS mode')
        if 'research only, no live entry' not in pre_text.lower():
            return _fail('premarket missing after-hours rule text')
        if 'prepare watchlist for next session' not in pre_text.lower():
            return _fail('premarket missing next-session action text')

        full_text = format_premarket_telegram(full=True, report=premarket_data)
        if 'AFTER-HOURS FULL BRIEF' not in full_text:
            return _fail('premarket full missing AFTER-HOURS FULL BRIEF title')

    print('AFTER_HOURS_PREMARKET_LABELS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
