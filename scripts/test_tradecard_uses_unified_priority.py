#!/usr/bin/env python3
"""Stage 50P — /tradecard uses unified_live_priority_engine.pick_tradecard_candidate."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_USES_UNIFIED_PRIORITY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/trading/trade_card_engine.py').read_text(encoding='utf-8')
    if 'pick_tradecard_candidate' not in src:
        return _fail('build_trade_card must call pick_tradecard_candidate')

    from backend.trading.trade_card_engine import build_trade_card

    fake_scanner = {
        'top_signals': [
            {'ticker': 'SONATSOFTW', 'change_percent': 4.0, 'volume_ratio': 1.5, 'strength': 'ULTRA',
             'direction': 'BULLISH', 'price': 800, 'day_high': 810, 'vwap': 790, 'open_price': 780},
        ],
    }
    pick_calls: list[str] = []

    def _pick(*, registry=None, scanner=None):
        pick_calls.append('unified')
        return 'SONATSOFTW', 'unified_catalyst_scanner'

    with patch('backend.trading.unified_live_priority_engine.pick_tradecard_candidate', side_effect=_pick), \
         patch('backend.trading.trade_card_engine._load_json', side_effect=lambda p: fake_scanner if 'scanner' in str(p) else {}), \
         patch('backend.trading.trade_card_engine._avoid_registry', return_value={}), \
         patch('backend.trading.trade_card_engine.TRADE_CARD_CACHE', PROJECT_ROOT / 'data' / '_test_tc_unified.json'):
        card = build_trade_card(persist=False, force_refresh=True)

    if not pick_calls:
        return _fail('pick_tradecard_candidate was not invoked')
    if card.get('ticker') != 'SONATSOFTW':
        return _fail(f"expected SONATSOFTW trade card got {card.get('ticker')!r}")
    if card.get('pick_reason') != 'unified_catalyst_scanner':
        return _fail(f"expected unified pick_reason got {card.get('pick_reason')!r}")

    print('TRADECARD_USES_UNIFIED_PRIORITY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
