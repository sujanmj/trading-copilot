#!/usr/bin/env python3
"""Stage 50R — /full Step 10 /tomorrow must match direct /tomorrow output."""

from __future__ import annotations

import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FRESH_META = {
    'scanner_fresh': True,
    'report_stale': True,
    'scanner_status': 'fresh',
    'report_status': 'stale',
}
SCANNER_SIGNALS = [
    {'ticker': 'DEVYANI', 'change_percent': 4.5, 'volume_ratio': 1.7, 'strength': 'ULTRA', 'direction': 'BULLISH', 'price': 180},
    {'ticker': 'WABAG', 'change_percent': 3.1, 'volume_ratio': 1.4, 'strength': 'STRONG', 'direction': 'BULLISH', 'price': 1500},
]
FAKE_FC = {
    'ok': True,
    'top_candidates': [{'ticker': 'AVANTIFEED', 'score': 92, 'decision': 'BUY_CANDIDATE'}],
}


def _fail(msg: str) -> int:
    print(f'FULL_TOMORROW_MATCHES_DIRECT_TOMORROW_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _patches():
    return (
        patch('backend.analytics.stock_decision_engine._load_sources', return_value={
            'final_confidence': FAKE_FC,
            'tomorrow_watchlist': {'ok': True, 'top_watchlist': []},
            'calibration': {},
            'scan': {'live_scanner': SCANNER_SIGNALS},
            'market': {'summary': {}},
            'global': {'summary': {}},
            'broker': {},
            'memory': {},
        }),
        patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value=FRESH_META),
        patch('backend.analytics.unified_decision_engine.build_live_rejection_set', return_value={}),
        patch('backend.analytics.unified_decision_engine.apply_my_feed_evidence', side_effect=lambda r, _: r),
        patch('backend.trading.unified_live_priority_engine._freshness_meta', return_value=FRESH_META),
        patch('backend.trading.unified_live_priority_engine._load_json', side_effect=lambda p: FAKE_FC if 'final_confidence' in str(p) else {}),
        patch('backend.trading.unified_live_priority_engine._live_registry', return_value={}),
        patch('backend.trading.unified_live_priority_engine._scanner_signals', return_value=SCANNER_SIGNALS),
        patch('backend.trading.unified_live_priority_engine._catalyst_priority_map', return_value={}),
        patch('backend.trading.trade_card_engine.detect_entry_missed', return_value=(False, [])),
        patch('backend.trading.trade_card_engine._compute_plan', side_effect=lambda row: {
            'price': float(row.get('price') or 100),
            'change_pct': float(row.get('change_percent') or 0),
            'volume_ratio': float(row.get('volume_ratio') or 1),
            'risk_reward': 2.0,
            'sl_pct': 0.8,
            'day_high': None,
            'vwap': None,
            'open_price': None,
        }),
    )


def main() -> int:
    from backend.analytics.unified_decision_engine import begin_unified_snapshot, end_unified_snapshot
    from backend.telegram.response_format import format_action_plan_telegram
    from backend.telegram.telegram_analysis_bot import _handle_stock_decision_command

    with ExitStack() as stack:
        for p in _patches():
            stack.enter_context(p)
        direct = _handle_stock_decision_command('tomorrow', cache_only=False)
        begin_unified_snapshot()
        try:
            _ = format_action_plan_telegram()
            full_step = _handle_stock_decision_command('tomorrow', cache_only=True)
        finally:
            end_unified_snapshot()

    if 'AVANTIFEED' in full_step:
        return _fail('/full Step 10 still shows stale AVANTIFEED')
    if direct.strip() != full_step.strip():
        return _fail('/full Step 10 body must match direct /tomorrow exactly')
    if 'AVANTIFEED' in direct:
        return _fail('direct /tomorrow must not show stale AVANTIFEED when scanner fresh')

    print('FULL_TOMORROW_MATCHES_DIRECT_TOMORROW_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
