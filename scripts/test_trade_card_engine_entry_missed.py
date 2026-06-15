#!/usr/bin/env python3
"""Stage 50L — trade card ENTRY_MISSED detection (TBOTEK example)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADE_CARD_ENGINE_ENTRY_MISSED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.trade_card_engine import build_trade_card, detect_entry_missed

    missed, reasons = detect_entry_missed(
        price=1490.0,
        change_pct=10.0,
        volume_ratio=1.0,
        day_high=1495.0,
        open_price=1350.0,
        risk_reward=1.2,
        sl_pct=5.0,
    )
    if not missed:
        return _fail('TBOTEK-like setup should detect entry missed')
    if not reasons:
        return _fail('expected missed reasons')

    scanner = {
        'top_signals': [{
            'ticker': 'TBOTEK',
            'price': 1490.0,
            'change_percent': 10.0,
            'volume_ratio': 1.0,
            'direction': 'BULLISH',
            'day_high': 1495.0,
            'open': 1350.0,
        }],
    }
    with patch('backend.trading.trade_card_engine._load_json', side_effect=lambda p: scanner if 'scanner' in str(p) else {}), \
         patch('backend.trading.trade_card_engine._avoid_registry', return_value={}), \
         patch('backend.trading.trade_card_engine.TRADE_CARD_CACHE', PROJECT_ROOT / 'data' / '_test_trade_card_missed.json'):
        card = build_trade_card('TBOTEK', persist=True, force_refresh=True)

    if card.get('status') != 'ENTRY_MISSED':
        return _fail(f'expected ENTRY_MISSED got {card.get("status")}')

    print('TRADE_CARD_ENGINE_ENTRY_MISSED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
