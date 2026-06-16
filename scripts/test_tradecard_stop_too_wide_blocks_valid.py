#!/usr/bin/env python3
"""Stage 50S — stop >1.2% blocks VALID_ENTRY even if reason mentions stop too wide."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_STOP_TOO_WIDE_BLOCKS_VALID_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.trade_card_engine import apply_tradecard_safety_gates

    wide_card = {
        'ok': True,
        'ticker': 'KPIL',
        'levels_source_ticker': 'KPIL',
        'status': 'VALID_ENTRY',
        'current_price': 612.2,
        'entry_zone': '604.85–615.14',
        'stop_loss': 569.96,
        'target_1': 685.66,
        'target_2': 722.4,
        'risk_reward': 2.0,
        'volume_ratio': 1.5,
        'reason': 'stop too wide (6.9%)',
        'paper_only': True,
    }

    with patch('backend.trading.trade_card_engine._is_after_hours_mode', return_value=False), \
         patch('backend.trading.trade_card_engine._is_live_market_hours', return_value=True), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=apply_tradecard_safety_gates(wide_card)), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('KPIL', 'VALID_ENTRY')):
        gated = apply_tradecard_safety_gates(wide_card)
        text = format_tradecard_telegram(explain=False)

    if gated.get('status') == 'VALID_ENTRY':
        return _fail('stop too wide card must not stay VALID_ENTRY')
    if 'VALID_ENTRY' in text:
        return _fail('formatted tradecard must not show VALID_ENTRY when stop too wide')
    if 'stop too wide' in text.lower() and 'VALID_ENTRY' in text:
        return _fail('stop too wide reason cannot coexist with VALID_ENTRY in output')
    if 'Entry zone:' in text and '569.96' in text:
        return _fail('must not show wide stop as actionable entry zone')

    print('TRADECARD_STOP_TOO_WIDE_BLOCKS_VALID_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
