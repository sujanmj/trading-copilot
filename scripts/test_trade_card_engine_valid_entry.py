#!/usr/bin/env python3
"""Stage 50L — trade card engine VALID_ENTRY path (explicit ticker; catalyst tested separately in 50N)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADE_CARD_ENGINE_VALID_ENTRY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.trade_card_engine import build_trade_card

    scanner = {
        'top_signals': [{
            'ticker': 'IXIGO',
            'price': 420.0,
            'change_percent': 2.4,
            'volume_ratio': 1.6,
            'direction': 'BULLISH',
            'strength': 'ULTRA',
        }],
    }
    required = (
        'ticker', 'status', 'current_price', 'entry_zone', 'stop_loss', 'target_1',
        'target_2', 'risk_reward', 'capital_plan', 'reason', 'invalid_if', 'exit_rule',
        'confidence', 'paper_only',
    )
    with patch('backend.trading.trade_card_engine._load_json', side_effect=lambda p: scanner if 'scanner' in str(p) else {}), \
         patch('backend.trading.trade_card_engine._avoid_registry', return_value={}), \
         patch('backend.trading.trade_card_engine.TRADE_CARD_CACHE', PROJECT_ROOT / 'data' / '_test_trade_card_valid.json'):
        card = build_trade_card('IXIGO', persist=True, force_refresh=True)

    for field in required:
        if field not in card:
            return _fail(f'missing field {field}')
    if card.get('paper_only') is not True:
        return _fail('paper_only must be true')
    if card.get('status') not in ('VALID_ENTRY', 'WAIT_FOR_PULLBACK', 'WAIT_FOR_VOLUME'):
        return _fail(f'unexpected status {card.get("status")}')
    if card.get('risk_reward', 0) < 1.5:
        return _fail('valid entry card should have RR >= 1.5')

    print('TRADE_CARD_ENGINE_VALID_ENTRY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
