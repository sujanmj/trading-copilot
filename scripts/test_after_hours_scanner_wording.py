#!/usr/bin/env python3
"""Unit tests — after-hours scanner next-session wording (Stage 48T)."""

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
    print(f'AFTER_HOURS_SCANNER_WORDING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.premarket_conviction import AFTER_HOURS_SCANNER_ACTION, format_premarket_telegram

    premarket_data = {
        'market_bias': 'Neutral',
        'top_setups': [{
            'ticker': 'EASEMYTRIP',
            'setup': 'BULLISH scanner signal',
            'score': 95,
            'source': 'scanner',
            'change_percent': 17.5,
            'reasons': [
                'prior-session scanner move +17.5% · vol 5.3x',
                AFTER_HOURS_SCANNER_ACTION,
            ],
        }],
        'avoid': [],
        'market_mode': AFTER_HOURS_MODE,
        'freshness_ok': True,
        'generated_at': datetime.now(IST).isoformat(),
    }

    with patch('backend.analytics.market_calendar_router.get_india_telegram_mode', return_value=AFTER_HOURS_MODE):
        text = format_premarket_telegram(full=False, report=premarket_data)

    lower = text.lower()
    if 'confirmed setup' in lower:
        return _fail('after-hours premarket must not say confirmed setup')
    if 'next-session watch' not in lower:
        return _fail('after-hours premarket must say next-session watch')
    if 'confirm tomorrow with price + volume' not in lower:
        return _fail('after-hours premarket must say confirm tomorrow with price + volume')
    if 'prior-session scanner move' not in lower:
        return _fail('after-hours scanner why must use prior-session wording')

    print('AFTER_HOURS_SCANNER_WORDING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
