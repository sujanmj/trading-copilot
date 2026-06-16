#!/usr/bin/env python3
"""Stage 50S — after-hours /tradecard cannot show VALID_ENTRY."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VALID_ENTRY = re.compile(r'\bVALID_ENTRY\b|·\s*<code>VALID_ENTRY</code>')


def _fail(msg: str) -> int:
    print(f'TRADECARD_NO_VALID_ENTRY_AFTER_HOURS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.trade_card_engine import apply_tradecard_safety_gates, build_trade_card

    fake_row = {
        'ticker': 'KPIL',
        'price': 500.0,
        'change_percent': 1.2,
        'volume_ratio': 1.5,
        'direction': 'BULLISH',
    }
    fake_card = {
        'ok': True,
        'session_date': '2099-01-01',
        'ticker': 'KPIL',
        'levels_source_ticker': 'KPIL',
        'status': 'VALID_ENTRY',
        'current_price': 500.0,
        'entry_zone': '498–502',
        'stop_loss': 494.0,
        'target_1': 505.0,
        'target_2': 508.0,
        'risk_reward': 2.0,
        'volume_ratio': 1.5,
        'reason': 'Price/volume/structure align for paper watch entry',
        'paper_only': True,
    }

    with patch('backend.trading.trade_card_engine._is_after_hours_mode', return_value=True), \
         patch('backend.trading.trade_card_engine._is_live_market_hours', return_value=False), \
         patch('backend.trading.trade_card_engine._pick_candidate', return_value=(fake_row, 'requested')), \
         patch('backend.trading.trade_card_engine._today', return_value='2099-01-01'), \
         patch('backend.trading.trade_card_engine._unified_today_top_ticker', return_value='KPIL'), \
         patch('backend.trading.trade_card_engine.TRADE_CARD_CACHE', PROJECT_ROOT / 'data' / '_test_trade_card_tmp.json'), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=apply_tradecard_safety_gates(fake_card)), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('KPIL', 'VALID_ENTRY')), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value='No live entry now. Next-session watch only.'):
        card = apply_tradecard_safety_gates(fake_card)
        text = format_tradecard_telegram(explain=False)
        built = build_trade_card(ticker='KPIL', force_refresh=True, persist=False)

    if card.get('status') == 'VALID_ENTRY':
        return _fail('safety gate must block VALID_ENTRY after hours')
    if VALID_ENTRY.search(text):
        return _fail('/tradecard text must not contain VALID_ENTRY after hours')
    if 'NEXT-SESSION WATCH' not in text and 'NO ACTIVE ENTRY' not in text:
        return _fail('after-hours tradecard must use next-session or no-active-entry wording')
    if built.get('status') == 'VALID_ENTRY':
        return _fail('build_trade_card must not emit VALID_ENTRY after hours')

    print('TRADECARD_NO_VALID_ENTRY_AFTER_HOURS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
