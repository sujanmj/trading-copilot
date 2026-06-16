#!/usr/bin/env python3
"""Stage 50S — scalp T1/T2/SL ranges enforced on live tradecard output."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_SCALP_TARGETS_ENFORCED_LIVE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.trade_card_engine import SCALP_T1_MAX_PCT, SCALP_T2_MAX_PCT, apply_tradecard_safety_gates

    wide_targets = {
        'ok': True,
        'ticker': 'KPIL',
        'levels_source_ticker': 'KPIL',
        'status': 'VALID_ENTRY',
        'current_price': 100.0,
        'entry_zone': '99–101',
        'stop_loss': 98.8,
        'target_1': 110.0,
        'target_2': 120.0,
        'risk_reward': 2.0,
        'volume_ratio': 1.5,
        'reason': 'test wide targets',
        'paper_only': True,
    }

    with patch('backend.trading.trade_card_engine._is_after_hours_mode', return_value=False), \
         patch('backend.trading.trade_card_engine._is_live_market_hours', return_value=True), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=apply_tradecard_safety_gates(wide_targets)), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('KPIL', 'VALID_ENTRY')):
        gated = apply_tradecard_safety_gates(wide_targets)
        text = format_tradecard_telegram(explain=False)

    t1_pct = (110.0 - 100.0) / 100.0 * 100
    if t1_pct <= SCALP_T1_MAX_PCT:
        return _fail('fixture must use out-of-range T1 for test')
    if gated.get('status') == 'VALID_ENTRY':
        return _fail('10%+ targets must block VALID_ENTRY')
    if '110' in text and 'T1:' in text:
        return _fail('must not display wide T1 as actionable')
    if 'VALID_ENTRY' in text:
        return _fail('scalp target violation must not show VALID_ENTRY')
    if SCALP_T2_MAX_PCT >= 2.0 and '120' in text and 'T2:' in text:
        return _fail('must not display wide T2 as actionable')

    print('TRADECARD_SCALP_TARGETS_ENFORCED_LIVE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
