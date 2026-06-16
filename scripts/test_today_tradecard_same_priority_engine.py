#!/usr/bin/env python3
"""Stage 50Q — /tradecard and /today share unified priority top pick."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FRESH_META = {'scanner_fresh': True, 'report_stale': True}
SCANNER_SIGNALS = [
    {'ticker': 'SONATSOFTW', 'change_percent': 4.2, 'volume_ratio': 1.6, 'strength': 'ULTRA', 'direction': 'BULLISH', 'price': 800},
    {'ticker': 'WABAG', 'change_percent': 3.1, 'volume_ratio': 1.4, 'strength': 'STRONG', 'direction': 'BULLISH', 'price': 1500},
]
FAKE_FC = {'ok': True, 'top_candidates': [{'ticker': 'AVANTIFEED', 'score': 92}]}
FAKE_SCANNER = {'top_signals': SCANNER_SIGNALS}


def _fail(msg: str) -> int:
    print(f'TODAY_TRADECARD_SAME_PRIORITY_ENGINE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.unified_live_priority_engine import build_unified_priority, pick_tradecard_candidate

    with patch('backend.trading.unified_live_priority_engine._freshness_meta', return_value=FRESH_META), \
         patch('backend.trading.unified_live_priority_engine._load_json', side_effect=lambda p: FAKE_FC if 'final_confidence' in str(p) else {}), \
         patch('backend.trading.unified_live_priority_engine._live_registry', return_value={}), \
         patch('backend.trading.unified_live_priority_engine._scanner_signals', return_value=SCANNER_SIGNALS), \
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
        unified = build_unified_priority(mode='today')
        today_top = str((unified.get('top_pick') or {}).get('ticker') or '').upper()
        tradecard_sym, reason = pick_tradecard_candidate(registry={}, scanner=FAKE_SCANNER)

    if not today_top:
        return _fail('unified today top_pick missing')
    if not tradecard_sym:
        return _fail('pick_tradecard_candidate returned no ticker')
    if today_top != str(tradecard_sym).upper():
        return _fail(f'today top {today_top!r} != tradecard pick {tradecard_sym!r}')
    if today_top == 'AVANTIFEED':
        return _fail('stale AVANTIFEED must not be unified top when scanner fresh')
    if reason not in ('unified_catalyst_scanner', 'unified_scanner', 'unified_fallback_scanner'):
        return _fail(f'unexpected pick reason {reason!r}')

    print('TODAY_TRADECARD_SAME_PRIORITY_ENGINE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
