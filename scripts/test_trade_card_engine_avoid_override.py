#!/usr/bin/env python3
"""Stage 50L — trade card AVOID override when ticker rejected."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADE_CARD_ENGINE_AVOID_OVERRIDE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.trade_card_engine import build_trade_card

    scanner = {
        'top_signals': [{
            'ticker': 'EASEMYTRIP',
            'price': 18.0,
            'change_percent': 3.0,
            'volume_ratio': 1.2,
            'direction': 'BULLISH',
        }],
    }
    with patch('backend.trading.trade_card_engine._load_json', side_effect=lambda p: scanner if 'scanner' in str(p) else {}), \
         patch('backend.trading.trade_card_engine._avoid_registry', return_value={'EASEMYTRIP': 'Avoid list'}), \
         patch('backend.trading.trade_card_engine.TRADE_CARD_CACHE', PROJECT_ROOT / 'data' / '_test_trade_card_avoid.json'):
        card = build_trade_card('EASEMYTRIP', persist=False, force_refresh=True)

    if card.get('status') != 'AVOID':
        return _fail(f'expected AVOID override, got {card.get("status")}')
    if 'Avoid/rejection override' not in str(card.get('reason') or ''):
        return _fail('reason should mention avoid override')

    print('TRADE_CARD_ENGINE_AVOID_OVERRIDE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
