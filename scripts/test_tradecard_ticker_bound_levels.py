#!/usr/bin/env python3
"""Stage 50S — tradecard blocks ticker/levels mismatch (KPIL vs ARVSMART)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_TICKER_BOUND_LEVELS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.trade_card_engine import apply_tradecard_safety_gates, get_trade_card

    mismatched = {
        'ok': True,
        'session_date': '2099-01-01',
        'ticker': 'KPIL',
        'levels_source_ticker': 'ARVSMART',
        'status': 'VALID_ENTRY',
        'current_price': 612.2,
        'entry_zone': '604.85–615.14',
        'stop_loss': 569.96,
        'target_1': 685.66,
        'target_2': 722.4,
        'risk_reward': 2.0,
        'reason': 'cached wrong ticker levels',
        'paper_only': True,
    }

    with patch('backend.trading.trade_card_engine._today', return_value='2099-01-01'), \
         patch('backend.trading.trade_card_engine._unified_today_top_ticker', return_value='KPIL'), \
         patch('backend.trading.trade_card_engine.TRADE_CARD_CACHE', PROJECT_ROOT / 'data' / '_test_trade_card_mismatch.json'), \
         patch('backend.trading.trade_card_engine._load_json', return_value=mismatched), \
         patch('backend.trading.trade_card_engine.build_trade_card', return_value=apply_tradecard_safety_gates(mismatched)), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('KPIL', 'NO_ACTIVE_ENTRY')):
        card = get_trade_card(rebuild=True)
        text = format_tradecard_telegram(explain=False)

    if card.get('status') == 'VALID_ENTRY':
        return _fail('levels_source mismatch must block VALID_ENTRY')
    if '612.2' in text and '569.96' in text:
        return _fail('must not show ARVSMART copied levels for KPIL')
    if 'ticker/price data mismatch' not in str(card.get('reason') or '').lower() and \
            'ticker/price data mismatch' not in text.lower():
        return _fail('must surface ticker/price data mismatch reason')

    print('TRADECARD_TICKER_BOUND_LEVELS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
