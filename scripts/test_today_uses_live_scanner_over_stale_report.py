#!/usr/bin/env python3
"""Stage 50P — /today prefers live scanner over stale final confidence."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TODAY_USES_LIVE_SCANNER_OVER_STALE_REPORT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.unified_live_priority_engine import build_unified_priority, format_today_unified

    fresh_meta = {
        'scanner_fresh': True,
        'report_stale': True,
        'scanner_status': 'fresh',
        'report_status': 'stale',
    }
    fake_scanner = {
        'top_signals': [
            {'ticker': 'SONATSOFTW', 'change_percent': 4.2, 'volume_ratio': 1.6, 'strength': 'ULTRA', 'direction': 'BULLISH', 'price': 800},
            {'ticker': 'WABAG', 'change_percent': 3.1, 'volume_ratio': 1.4, 'strength': 'STRONG', 'direction': 'BULLISH', 'price': 1500},
            {'ticker': 'ARVSMART', 'change_percent': 2.8, 'volume_ratio': 1.2, 'strength': 'WATCH', 'direction': 'BULLISH', 'price': 700},
        ],
    }
    fake_fc = {
        'ok': True,
        'top_candidates': [
            {'ticker': 'AVANTIFEED', 'score': 92, 'change_percent': 1.0, 'volume_ratio': 0.9},
        ],
    }
    fake_catalyst = {'priority_list': [], 'items': []}

    with patch('backend.trading.unified_live_priority_engine._freshness_meta', return_value=fresh_meta), \
         patch('backend.trading.unified_live_priority_engine._load_json', side_effect=lambda p: fake_fc if 'final_confidence' in str(p) else {}), \
         patch('backend.trading.unified_live_priority_engine._live_registry', return_value={}), \
         patch('backend.trading.unified_live_priority_engine._scanner_signals', return_value=fake_scanner['top_signals']), \
         patch('backend.trading.unified_live_priority_engine._catalyst_priority_map', return_value={}), \
         patch('backend.trading.trade_card_engine.detect_entry_missed', return_value=(False, [])), \
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
        text = format_today_unified(payload)

    top = (payload.get('top_pick') or {}).get('ticker')
    ranked = [str(r.get('ticker') or '').upper() for r in payload.get('ranked_candidates') or []]

    if 'AVANTIFEED' in ranked:
        return _fail('stale AVANTIFEED must not appear when scanner fresh and report stale')
    if top not in ('SONATSOFTW', 'WABAG', 'ARVSMART', 'KPIL', 'LALPATHLAB'):
        return _fail(f'expected live scanner top got {top!r}')
    if 'SONATSOFTW' not in text and 'NO VALID ENTRY NOW' not in text:
        return _fail('today unified text must reference live scanner leader or no-entry state')

    print('TODAY_USES_LIVE_SCANNER_OVER_STALE_REPORT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
