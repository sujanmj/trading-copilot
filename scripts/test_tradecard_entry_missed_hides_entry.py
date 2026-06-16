#!/usr/bin/env python3
"""Stage 50O — ENTRY_MISSED hides actionable entry/SL/targets."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_ENTRY_MISSED_HIDES_ENTRY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.trade_card_engine import build_trade_card

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
         patch('backend.trading.trade_card_engine.TRADE_CARD_CACHE', PROJECT_ROOT / 'data' / '_test_tc_missed_hide.json'):
        card = build_trade_card('TBOTEK', persist=True, force_refresh=True)

    if card.get('status') != 'ENTRY_MISSED':
        return _fail(f'expected ENTRY_MISSED got {card.get("status")}')
    if card.get('entry_zone') != 'NO ACTIVE ENTRY':
        return _fail('ENTRY_MISSED must hide entry zone')
    if card.get('stop_loss') is not None:
        return _fail('ENTRY_MISSED must not expose actionable stop')

    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False):
        text = format_tradecard_telegram(explain=False)

    if 'NO ACTIVE ENTRY' not in text:
        return _fail('telegram output must show NO ACTIVE ENTRY')
    if 'Stop: 4' in text or 'Stop: 1' in text.split('Research')[0]:
        if 'Ref SL' not in text and card.get('stop_loss') is None:
            if 'Stop:' in text and 'Stop: —' not in text and 'Stop: None' not in text:
                # allow Stop: — only
                if 'Stop: —' not in text:
                    return _fail('must not show tradable stop in ENTRY_MISSED view')

    print('TRADECARD_ENTRY_MISSED_HIDES_ENTRY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
