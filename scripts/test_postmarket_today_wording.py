#!/usr/bin/env python3
"""Stage 50Q — post-market /today uses next-session watch wording."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCANNER_SIGNALS = [
    {'ticker': 'SONATSOFTW', 'change_percent': 4.2, 'volume_ratio': 1.6, 'strength': 'ULTRA', 'direction': 'BULLISH', 'price': 800},
    {'ticker': 'WABAG', 'change_percent': 3.1, 'volume_ratio': 1.4, 'strength': 'STRONG', 'direction': 'BULLISH', 'price': 1500},
    {'ticker': 'KPIL', 'change_percent': 2.9, 'volume_ratio': 1.3, 'strength': 'STRONG', 'direction': 'BULLISH', 'price': 900},
]


def _fail(msg: str) -> int:
    print(f'POSTMARKET_TODAY_WORDING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.unified_live_priority_engine import build_unified_priority, format_decision_unified

    fresh_meta = {'scanner_fresh': True, 'report_stale': True}
    fake_fc = {'ok': True, 'top_candidates': [{'ticker': 'AVANTIFEED', 'score': 92}]}

    with patch('backend.trading.unified_live_priority_engine._freshness_meta', return_value=fresh_meta), \
         patch('backend.trading.unified_live_priority_engine._is_postmarket_mode', return_value=True), \
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
        payload = build_unified_priority(mode='today')
        text = format_decision_unified(payload, mode='today')

    required = [
        'POST-MARKET REVIEW / NEXT-SESSION WATCH',
        'Top fresh scanner names:',
        'SONATSOFTW — entry missed / next-session watch',
        'WABAG — entry missed / next-session watch',
        'KPIL — entry missed / next-session watch',
        'No live entry now. Wait for next session confirmation.',
    ]
    for token in required:
        if token not in text:
            return _fail(f'missing post-market wording: {token!r}')
    if 'Top candidate:' in text:
        return _fail('post-market /today must not use actionable Top candidate wording')

    print('POSTMARKET_TODAY_WORDING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
