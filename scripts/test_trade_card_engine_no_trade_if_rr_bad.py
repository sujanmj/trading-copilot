#!/usr/bin/env python3
"""Stage 50L — trade card NO_TRADE when RR below minimum."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADE_CARD_ENGINE_NO_TRADE_IF_RR_BAD_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading import trade_card_engine as tce

    scanner = {
        'top_signals': [{
            'ticker': 'WEAKRR',
            'price': 100.0,
            'change_percent': 0.5,
            'volume_ratio': 2.0,
            'direction': 'BULLISH',
        }],
    }

    def fake_plan(row):
        return {
            'entry_zone': '99–101',
            'stop_loss': 90.0,
            'target_1': 102.0,
            'target_2': 104.0,
            'risk_reward': 0.22,
            'sl_pct': 2.0,
            'price': 100.0,
            'change_pct': 0.5,
            'volume_ratio': 2.0,
        }

    with patch.object(tce, '_load_json', side_effect=lambda p: scanner if 'scanner' in str(p) else {}), \
         patch.object(tce, '_avoid_registry', return_value={}), \
         patch.object(tce, '_compute_plan', side_effect=fake_plan), \
         patch.object(tce, 'TRADE_CARD_CACHE', PROJECT_ROOT / 'data' / '_test_trade_card_rr.json'):
        card = tce.build_trade_card(force_refresh=True, persist=False)

    if card.get('status') != 'NO_TRADE':
        return _fail(f'expected NO_TRADE for bad RR, got {card.get("status")}')

    print('TRADE_CARD_ENGINE_NO_TRADE_IF_RR_BAD_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
