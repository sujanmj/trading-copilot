#!/usr/bin/env python3
"""Stage 50R — after-hours /today uses post-market review wording."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FRESH_META = {'scanner_fresh': True, 'report_stale': True}
SCANNER_SIGNALS = [
    {'ticker': 'DEVYANI', 'change_percent': 4.5, 'volume_ratio': 1.7, 'strength': 'ULTRA', 'direction': 'BULLISH', 'price': 180},
]
FAKE_FC = {'ok': True, 'top_candidates': [{'ticker': 'AVANTIFEED', 'score': 92}]}


def _fail(msg: str) -> int:
    print(f'AFTERHOURS_TODAY_POSTMARKET_LABEL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.stock_decision_engine import build_stock_decision
    from backend.telegram.response_format import format_stock_decision_payload
    from backend.telegram.telegram_analysis_bot import _handle_stock_decision_command

    with patch('backend.analytics.stock_decision_engine._load_sources', return_value={
        'final_confidence': FAKE_FC,
        'tomorrow_watchlist': {'ok': True, 'top_watchlist': []},
        'calibration': {},
        'scan': {'live_scanner': SCANNER_SIGNALS},
        'market': {'summary': {}},
        'global': {'summary': {}},
        'broker': {},
        'memory': {},
    }), patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value=FRESH_META), \
         patch('backend.analytics.unified_decision_engine.build_live_rejection_set', return_value={}), \
         patch('backend.analytics.unified_decision_engine.is_unified_snapshot_active', return_value=False), \
         patch('backend.analytics.unified_decision_engine.apply_my_feed_evidence', side_effect=lambda r, _: r), \
         patch('backend.trading.unified_live_priority_engine._freshness_meta', return_value=FRESH_META), \
         patch('backend.trading.unified_live_priority_engine._is_postmarket_mode', return_value=True), \
         patch('backend.trading.unified_live_priority_engine._load_json', side_effect=lambda p: FAKE_FC if 'final_confidence' in str(p) else {}), \
         patch('backend.trading.unified_live_priority_engine._live_registry', return_value={}), \
         patch('backend.trading.unified_live_priority_engine._scanner_signals', return_value=SCANNER_SIGNALS), \
         patch('backend.trading.unified_live_priority_engine._catalyst_priority_map', return_value={}), \
         patch('backend.trading.trade_card_engine.detect_entry_missed', return_value=(True, [])), \
         patch('backend.trading.trade_card_engine._compute_plan', side_effect=lambda row: {
             'price': float(row.get('price') or 100),
             'change_pct': float(row.get('change_percent') or 0),
             'volume_ratio': float(row.get('volume_ratio') or 1),
             'risk_reward': 2.0,
             'sl_pct': 0.8,
             'day_high': None,
             'vwap': None,
             'open_price': None,
         }):
        payload = build_stock_decision(mode='today')
        formatted = format_stock_decision_payload(payload, 'today')
        direct = _handle_stock_decision_command('today', cache_only=False)

    required = [
        'POST-MARKET REVIEW / NEXT-SESSION WATCH',
        'No live entry now',
    ]
    for token in required:
        if token not in formatted:
            return _fail(f'missing post-market wording in formatted payload: {token!r}')
        if token not in direct:
            return _fail(f'missing post-market wording in direct handler: {token!r}')
    if 'Top candidate:' in formatted:
        return _fail('post-market /today must not use actionable Top candidate wording')

    print('AFTERHOURS_TODAY_POSTMARKET_LABEL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
