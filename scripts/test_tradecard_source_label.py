#!/usr/bin/env python3
"""Stage 50T — /tradecard and /today include scanner/catalyst source label."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_SOURCE_LABEL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.unified_live_priority_engine import format_today_unified

    fake_card = {
        'ok': True,
        'ticker': 'SUNDRMFAST',
        'levels_source_ticker': 'SUNDRMFAST',
        'status': 'NEXT_SESSION_WATCH',
        'entry_zone': 'NO ACTIVE ENTRY',
        'reason': 'market closed/after-hours',
        'after_hours': True,
        'paper_only': True,
    }

    payload = {
        'decision': 'WATCH_FOR_ENTRY',
        'top_pick': {'ticker': 'SUNDRMFAST', 'action': 'WATCH_FOR_ENTRY', 'unified_score': 75, 'why': [], 'risk': []},
        'ranked_candidates': [],
    }

    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.trading.trade_card_engine.apply_tradecard_safety_gates', side_effect=lambda c: c), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('SUNDRMFAST', 'NO_ACTIVE_ENTRY')), \
         patch('backend.trading.unified_live_priority_engine.decision_source_label', return_value='Source: scanner-confirmed'), \
         patch('backend.trading.unified_live_priority_engine._is_postmarket_mode', return_value=False):
        tradecard = format_tradecard_telegram(explain=False)
        today = format_today_unified(payload)

    if 'Source: scanner-confirmed' not in tradecard:
        return _fail('/tradecard must include Source: scanner-confirmed')
    if 'Source: scanner-confirmed' not in today:
        return _fail('/today must include source label')
    if 'VALID_ENTRY' in tradecard:
        return _fail('after-hours tradecard must not show VALID_ENTRY')

    with patch('backend.trading.unified_live_priority_engine.decision_source_label', return_value='Source: catalyst-backed + scanner-confirmed'):
        backed = format_today_unified(payload)
    if 'Source: catalyst-backed + scanner-confirmed' not in backed:
        return _fail('catalyst-backed label must render when returned by engine')

    print('TRADECARD_SOURCE_LABEL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
