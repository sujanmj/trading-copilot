#!/usr/bin/env python3
"""Stage 50Z — premarket tradecard wording must not say after-hours."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_PREMARKET_WORDING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram

    card = {
        'ok': True,
        'session_date': '2026-06-19',
        'ticker': 'ROSSARI',
        'levels_source_ticker': 'ROSSARI',
        'status': 'NO_ACTIVE_ENTRY',
        'current_price': 554.25,
        'entry_zone': '553.00–556.00',
        'stop_loss': 550.0,
        'target_1': 560.0,
        'target_2': 565.0,
        'reason': 'market not open for confirmed entry yet',
        'paper_only': True,
        'generated_at': '2026-06-19T08:30:00+05:30',
    }

    with patch('backend.telegram.india_mode_lock.is_premarket_phase', return_value=True), \
         patch('backend.telegram.response_format._is_tradecard_premarket_phase', return_value=True), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('ROSSARI', 'NO_ACTIVE_ENTRY')), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''), \
         patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False):
        text = format_tradecard_telegram(explain=False, freshness_meta={'quote_age_seconds': 45, 'scanner_age_seconds': 30})

    upper = text.upper()
    if 'PREMARKET WATCH' not in upper:
        return _fail('must show PREMARKET WATCH header')
    if 'ROSSARI' not in text:
        return _fail('must include ticker')
    if 'market not open for confirmed entry yet' not in text:
        return _fail('must use premarket reason')
    if 'confirm after 09:20' not in text:
        return _fail('must include 09:20 confirmation plan')
    for banned in ('market closed', 'after-hours', 'NEXT-SESSION WATCH'):
        if banned.lower() in text.lower():
            return _fail(f'must not say {banned!r} during premarket')

    print('TRADECARD_PREMARKET_WORDING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
