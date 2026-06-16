#!/usr/bin/env python3
"""Stage 50N — /catalysts telegram command formatting."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FORBIDDEN = re.compile(r'\b(guaranteed|99%|sure win)\b', re.IGNORECASE)
NAKED_BUY_SELL = re.compile(r'\bAction:\s*(BUY|SELL)\b', re.IGNORECASE)


def _fail(msg: str) -> int:
    print(f'CATALYST_RADAR_TELEGRAM_COMMAND_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import format_catalyst_radar_telegram, format_preopen_catalyst_watchlist
    from backend.telegram.lazy_command_runner import run_catalysts_only

    fake_radar = {
        'priority_list': [{
            'ticker': 'HCLTECH',
            'side': 'BULLISH',
            'catalyst_type': 'ACQUISITION',
            'freshness_label': 'today',
            'change_pct': 3.1,
            'volume_ratio': 1.2,
            'priority': 'HIGH',
            'trade_status': 'WAIT FOR VOLUME',
        }],
        'bullish_watch': [{'ticker': 'HCLTECH', 'catalyst_type': 'ACQUISITION'}],
        'avoid_list': [{'ticker': 'GICRE', 'catalyst_type': 'OFS'}],
        'items': [],
    }
    with patch('backend.intelligence.stock_catalyst_radar.build_catalyst_radar', return_value=fake_radar), \
         patch('backend.intelligence.stock_catalyst_radar.get_catalyst_radar', return_value=fake_radar):
        text = format_catalyst_radar_telegram()
        preopen = format_preopen_catalyst_watchlist()
        result = run_catalysts_only('today')

    if 'STOCK CATALYST RADAR' not in text:
        return _fail('missing radar header')
    if 'HCLTECH' not in text:
        return _fail('missing ticker in radar output')
    if FORBIDDEN.search(text) or FORBIDDEN.search(preopen):
        return _fail('forbidden guaranteed language')
    if NAKED_BUY_SELL.search(text):
        return _fail('naked BUY/SELL in catalyst output')
    if 'CATALYST WATCHLIST' not in preopen:
        return _fail('preopen watchlist header missing')
    if result.get('scope') != 'catalysts':
        return _fail('run_catalysts_only scope must be catalysts')

    print('CATALYST_RADAR_TELEGRAM_COMMAND_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
