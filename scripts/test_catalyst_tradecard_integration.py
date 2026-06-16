#!/usr/bin/env python3
"""Stage 50N — tradecard prefers catalyst-confirmed tickers."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CATALYST_TRADECARD_INTEGRATION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.trade_card_engine import build_trade_card

    scanner = {
        'top_signals': [
            {
                'ticker': 'LOWPRIO',
                'price': 100.0,
                'change_percent': 5.0,
                'volume_ratio': 2.0,
                'direction': 'BULLISH',
                'strength': 'ULTRA',
            },
            {
                'ticker': 'HCLTECH',
                'price': 1600.0,
                'change_percent': 2.5,
                'volume_ratio': 1.5,
                'direction': 'BULLISH',
                'strength': 'STRONG',
            },
        ],
    }
    fake_radar = {
        'priority_list': [{
            'ticker': 'HCLTECH',
            'side': 'BULLISH',
            'priority': 'HIGH',
            'score': 78,
            'trade_status': 'VALID ENTRY WATCH',
        }],
        'items': [],
    }

    with patch('backend.trading.trade_card_engine._load_json', side_effect=lambda p: scanner if 'scanner' in str(p) else {}), \
         patch('backend.trading.trade_card_engine._avoid_registry', return_value={}), \
         patch('backend.intelligence.stock_catalyst_radar.get_catalyst_radar', return_value=fake_radar), \
         patch('backend.intelligence.stock_catalyst_radar._scanner_quote', side_effect=lambda t: next(
             (s for s in scanner['top_signals'] if s['ticker'] == t), {}
         )), \
         patch('backend.trading.trade_card_engine.TRADE_CARD_CACHE', PROJECT_ROOT / 'data' / '_test_catalyst_tc.json'):
        card = build_trade_card(persist=True, force_refresh=True)

    if card.get('ticker') != 'HCLTECH':
        return _fail(f'expected HCLTECH catalyst pick got {card.get("ticker")}')
    if card.get('pick_reason') != 'catalyst_confirmed':
        return _fail(f'expected catalyst_confirmed pick_reason got {card.get("pick_reason")}')
    if card.get('paper_only') is not True:
        return _fail('paper_only must remain true')

    print('CATALYST_TRADECARD_INTEGRATION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
