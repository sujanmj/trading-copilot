#!/usr/bin/env python3
"""Stage 50R — /tradecard evaluates unified /today top before other scanner names."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FRESH_META = {'scanner_fresh': True, 'report_stale': True}
SCANNER_SIGNALS = [
    {'ticker': 'ARVSMART', 'change_percent': 3.2, 'volume_ratio': 1.5, 'strength': 'STRONG', 'direction': 'BULLISH', 'price': 700},
    {'ticker': 'SONATSOFTW', 'change_percent': 4.2, 'volume_ratio': 1.6, 'strength': 'ULTRA', 'direction': 'BULLISH', 'price': 800},
]
CATALYST_MAP = {
    'DEVYANI': {
        'ticker': 'DEVYANI',
        'score': 88,
        'catalyst_type': 'ORDER_WIN',
        'side': 'BULLISH',
    },
}
FAKE_FC = {'ok': True, 'top_candidates': [{'ticker': 'AVANTIFEED', 'score': 92}]}
FAKE_SCANNER = {'top_signals': SCANNER_SIGNALS}


def _fail(msg: str) -> int:
    print(f'TRADECARD_EVALUATES_TODAY_TOP_FIRST_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.trade_card_engine import build_trade_card
    from backend.trading.unified_live_priority_engine import build_unified_priority, pick_tradecard_candidate

    stale_card = {
        'ok': True,
        'session_date': '2099-01-01',
        'ticker': 'ARVSMART',
        'status': 'NO_TRADE',
        'reason': 'cached other name',
    }

    with patch('backend.trading.unified_live_priority_engine._freshness_meta', return_value=FRESH_META), \
         patch('backend.trading.unified_live_priority_engine._load_json', side_effect=lambda p: FAKE_FC if 'final_confidence' in str(p) else FAKE_SCANNER if 'scanner' in str(p) else {}), \
         patch('backend.trading.unified_live_priority_engine._live_registry', return_value={}), \
         patch('backend.trading.unified_live_priority_engine._scanner_signals', return_value=SCANNER_SIGNALS), \
         patch('backend.trading.unified_live_priority_engine._catalyst_priority_map', return_value=CATALYST_MAP), \
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
         }), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=stale_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.trading.trade_card_engine._today', return_value='2099-01-01'):
        unified = build_unified_priority(mode='today')
        today_top = str((unified.get('top_pick') or {}).get('ticker') or '').upper()
        picked, reason = pick_tradecard_candidate(registry={}, scanner=FAKE_SCANNER)
        text = format_tradecard_telegram(explain=False)
        card = build_trade_card(force_refresh=True)

    if today_top != 'DEVYANI':
        return _fail(f'expected unified today top DEVYANI got {today_top!r}')
    if str(picked or '').upper() != 'DEVYANI':
        return _fail(f'pick_tradecard_candidate must return DEVYANI got {picked!r} reason={reason!r}')
    if reason not in ('unified_today_top', 'unified_catalyst_scanner', 'unified_scanner'):
        return _fail(f'unexpected pick reason {reason!r}')
    if 'DEVYANI' not in text:
        return _fail('/tradecard output must evaluate DEVYANI first')
    if 'ARVSMART' in text and 'DEVYANI' not in text:
        return _fail('/tradecard must not silently switch to ARVSMART')
    if str(card.get('ticker') or '').upper() != 'DEVYANI':
        return _fail(f'build_trade_card ticker must be DEVYANI got {card.get("ticker")!r}')

    print('TRADECARD_EVALUATES_TODAY_TOP_FIRST_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
