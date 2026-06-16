#!/usr/bin/env python3
"""Stage 50Q — /today must not surface stale AVANTIFEED when scanner is fresh."""

from __future__ import annotations

import sys
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
    {'ticker': 'SONATSOFTW', 'change_percent': 4.2, 'volume_ratio': 1.6, 'strength': 'ULTRA', 'direction': 'BULLISH', 'price': 800},
    {'ticker': 'WABAG', 'change_percent': 3.1, 'volume_ratio': 1.4, 'strength': 'STRONG', 'direction': 'BULLISH', 'price': 1500},
    {'ticker': 'KPIL', 'change_percent': 2.9, 'volume_ratio': 1.3, 'strength': 'STRONG', 'direction': 'BULLISH', 'price': 900},
    {'ticker': 'ARVSMART', 'change_percent': 2.8, 'volume_ratio': 1.2, 'strength': 'WATCH', 'direction': 'BULLISH', 'price': 700},
    {'ticker': 'BRIGADE', 'change_percent': 2.5, 'volume_ratio': 1.1, 'strength': 'WATCH', 'direction': 'BULLISH', 'price': 1100},
]
FAKE_FC = {
    'ok': True,
    'top_candidates': [
        {'ticker': 'AVANTIFEED', 'score': 92, 'change_percent': 1.0, 'volume_ratio': 0.9, 'decision': 'BUY_CANDIDATE'},
    ],
}


def _fail(msg: str) -> int:
    print(f'TODAY_NO_STALE_CANDIDATE_WHEN_SCANNER_FRESH_TEST_FAIL: {msg}', file=sys.stderr)
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
        patch('backend.analytics.unified_decision_engine.is_unified_snapshot_active', return_value=False),
        patch('backend.analytics.unified_decision_engine.apply_my_feed_evidence', side_effect=lambda r, _: r),
        patch('backend.trading.unified_live_priority_engine._freshness_meta', return_value=FRESH_META),
        patch('backend.trading.unified_live_priority_engine._load_json', side_effect=lambda p: FAKE_FC if 'final_confidence' in str(p) else {}),
        patch('backend.trading.unified_live_priority_engine._live_registry', return_value={}),
        patch('backend.trading.unified_live_priority_engine._scanner_signals', return_value=SCANNER_SIGNALS),
        patch('backend.trading.unified_live_priority_engine._catalyst_priority_map', return_value={}),
        patch('backend.trading.trade_card_engine.detect_entry_missed', return_value=(True, [])),
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
    from backend.analytics.stock_decision_engine import build_stock_decision

    with _patches()[0], _patches()[1], _patches()[2], _patches()[3], _patches()[4], \
         _patches()[5], _patches()[6], _patches()[7], _patches()[8], _patches()[9], _patches()[10], _patches()[11]:
        payload = build_stock_decision(mode='today')

    if payload.get('ok') is not True:
        return _fail(f'build_stock_decision failed: {payload.get("error")}')
    if not payload.get('unified_priority'):
        return _fail('expected unified_priority delegation when scanner fresh')

    ranked = [str(r.get('ticker') or '').upper() for r in payload.get('ranked_candidates') or []]
    top = str((payload.get('top_pick') or {}).get('ticker') or '').upper()
    text = str(payload.get('telegram_message') or '')

    if 'AVANTIFEED' in ranked or top == 'AVANTIFEED' or 'AVANTIFEED' in text:
        return _fail('stale AVANTIFEED must not appear in /today when scanner fresh')
    live_names = {'SONATSOFTW', 'WABAG', 'KPIL', 'ARVSMART', 'BRIGADE'}
    if top not in live_names and 'NO VALID ENTRY NOW' not in text and 'No clean candidate' not in text:
        return _fail(f'expected live scanner top or no-entry state got {top!r}')

    print('TODAY_NO_STALE_CANDIDATE_WHEN_SCANNER_FRESH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
