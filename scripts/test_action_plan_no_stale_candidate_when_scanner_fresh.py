#!/usr/bin/env python3
"""Stage 50Q — /action plan must not surface stale AVANTIFEED when scanner is fresh."""

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
    'lines': {'report': 'Report: stale', 'scanner': 'Scanner: fresh', 'news': 'News: fresh'},
}
SCANNER_SIGNALS = [
    {'ticker': 'SONATSOFTW', 'change_percent': 4.2, 'volume_ratio': 1.6, 'strength': 'ULTRA', 'direction': 'BULLISH', 'price': 800},
    {'ticker': 'WABAG', 'change_percent': 3.1, 'volume_ratio': 1.4, 'strength': 'STRONG', 'direction': 'BULLISH', 'price': 1500},
]
STALE_TODAY = {
    'ok': True,
    'mode': 'today',
    'decision': 'BUY_CANDIDATE',
    'top_pick': {'ticker': 'AVANTIFEED', 'action': 'BUY_CANDIDATE', 'score': 92, 'confidence': 'HIGH', 'why': ['stale']},
    'ranked_candidates': [{'ticker': 'AVANTIFEED', 'action': 'BUY_CANDIDATE', 'score': 92}],
    'avoid': [],
    'telegram_message': 'AVANTIFEED stale',
}
STALE_TOMORROW = {
    'ok': True,
    'mode': 'tomorrow',
    'decision': 'WATCH_FOR_ENTRY',
    'top_pick': {'ticker': 'AVANTIFEED', 'action': 'WATCH_FOR_ENTRY', 'score': 80, 'confidence': 'MEDIUM', 'why': ['stale']},
    'ranked_candidates': [{'ticker': 'AVANTIFEED', 'action': 'WATCH_FOR_ENTRY', 'score': 80}],
    'avoid': [],
}


def _fail(msg: str) -> int:
    print(f'ACTION_PLAN_NO_STALE_CANDIDATE_WHEN_SCANNER_FRESH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.unified_live_priority_engine import build_unified_priority

    fake_fc = {
        'ok': True,
        'top_candidates': [{'ticker': 'AVANTIFEED', 'score': 92}],
    }

    with patch('backend.analytics.railway_decision_bootstrap.repair_decision_for_telegram', side_effect=lambda m: (STALE_TODAY if m == 'today' else STALE_TOMORROW, False, False)), \
         patch('backend.analytics.railway_decision_bootstrap.load_cached_stock_decision', side_effect=lambda m: STALE_TODAY if m == 'today' else STALE_TOMORROW), \
         patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value=FRESH_META), \
         patch('backend.analytics.unified_decision_engine.apply_live_guard_to_payload', side_effect=lambda p: p), \
         patch('backend.analytics.unified_decision_engine.note_snapshot_pick'), \
         patch('backend.analytics.aihub_tab_payloads.build_brain_payload', return_value={'summary': {}}), \
         patch('backend.analytics.aihub_tab_payloads.build_market_payload', return_value={'summary': {}}), \
         patch('backend.analytics.aihub_tab_payloads.build_global_payload', return_value={'summary': {}}), \
         patch('backend.telegram.lazy_command_runner._load_json', return_value={}), \
         patch('backend.trading.unified_live_priority_engine._freshness_meta', return_value=FRESH_META), \
         patch('backend.trading.unified_live_priority_engine._load_json', side_effect=lambda p: fake_fc if 'final_confidence' in str(p) else {}), \
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
        unified = build_unified_priority(mode='today')
        from backend.telegram.response_format import format_action_plan_telegram

        text = format_action_plan_telegram()

    if 'AVANTIFEED' in text:
        return _fail('action plan must not mention stale AVANTIFEED when scanner fresh')
    top = (unified.get('top_pick') or {}).get('ticker')
    if top and top not in text and 'NO VALID ENTRY NOW' not in text and 'No clean candidate' not in text:
        return _fail(f'unified top {top!r} not reflected in action plan text')

    print('ACTION_PLAN_NO_STALE_CANDIDATE_WHEN_SCANNER_FRESH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
