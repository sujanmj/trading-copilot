#!/usr/bin/env python3
"""Stage 50N — bearish/avoid catalyst cannot become VALID_ENTRY tradecard."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CATALYST_AVOID_OVERRIDES_TRADECARD_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.trade_card_engine import build_trade_card

    scanner = {
        'top_signals': [{
            'ticker': 'GICRE',
            'price': 400.0,
            'change_percent': -6.0,
            'volume_ratio': 1.8,
            'direction': 'BEARISH',
            'strength': 'ULTRA',
        }],
    }
    fake_radar = {
        'priority_list': [{
            'ticker': 'GICRE',
            'side': 'BEARISH',
            'priority': 'AVOID',
            'score': 30,
            'trade_status': 'AVOID/RISK',
        }],
        'items': [],
    }

    with patch('backend.trading.trade_card_engine._load_json', side_effect=lambda p: scanner if 'scanner' in str(p) else {}), \
         patch('backend.trading.trade_card_engine._avoid_registry', return_value={'GICRE': 'OFS overhang'}), \
         patch('backend.intelligence.stock_catalyst_radar.get_catalyst_radar', return_value=fake_radar), \
         patch('backend.intelligence.stock_catalyst_radar.pick_catalyst_tradecard_candidate', return_value=(None, 'no_catalyst_candidate')), \
         patch('backend.trading.trade_card_engine.TRADE_CARD_CACHE', PROJECT_ROOT / 'data' / '_test_catalyst_avoid.json'):
        card = build_trade_card(ticker='GICRE', persist=True, force_refresh=True)

    if card.get('status') != 'AVOID':
        return _fail(f'bearish avoid catalyst must stay AVOID got {card.get("status")}')
    if card.get('status') == 'VALID_ENTRY':
        return _fail('avoid catalyst must never become VALID_ENTRY')

    print('CATALYST_AVOID_OVERRIDES_TRADECARD_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
