#!/usr/bin/env python3
"""Stage 50V hotfix — /tradecard renders engine source_label exactly."""

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


def _base_card(**extra):
    card = {
        'ok': True,
        'ticker': 'SUNDRMFAST',
        'levels_source_ticker': 'SUNDRMFAST',
        'status': 'NEXT_SESSION_WATCH',
        'entry_zone': 'NO ACTIVE ENTRY',
        'reason': 'market closed/after-hours',
        'after_hours': True,
        'paper_only': True,
    }
    card.update(extra)
    return card


def _format_tradecard(card, *, explain=False, freshness=None):
    from backend.telegram.response_format import format_tradecard_telegram

    patches = [
        patch('backend.trading.trade_card_engine.get_trade_card', return_value=card),
        patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False),
        patch('backend.trading.trade_card_engine.apply_tradecard_safety_gates', side_effect=lambda c: c),
        patch(
            'backend.telegram.response_format._tradecard_unified_today_top',
            return_value=('SUNDRMFAST', 'NO_ACTIVE_ENTRY'),
        ),
        patch('backend.trading.unified_live_priority_engine._is_postmarket_mode', return_value=False),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        return format_tradecard_telegram(explain=explain, freshness_meta=freshness or {})


def main() -> int:
    from backend.trading.unified_live_priority_engine import format_today_unified

    freshness = {'quote_age_seconds': 0, 'scanner_age_seconds': 12, 'quote_refreshed': True}

    scanner_card = _base_card(source_label='Source: scanner-confirmed')
    tradecard = _format_tradecard(scanner_card, freshness=freshness)
    if 'Source: scanner-confirmed' not in tradecard:
        return _fail('/tradecard must include Source: scanner-confirmed')
    if 'Freshness:' not in tradecard:
        return _fail('/tradecard must keep 50V Freshness line')
    if 'VALID_ENTRY' in tradecard:
        return _fail('after-hours tradecard must not show VALID_ENTRY')

    backed_card = _base_card(source_label='Source: catalyst-backed + scanner-confirmed')
    tradecard_backed = _format_tradecard(backed_card, freshness=freshness)
    if 'Source: catalyst-backed + scanner-confirmed' not in tradecard_backed:
        return _fail('catalyst-backed label must render when returned by engine')
    if 'Source: scanner-confirmed' in tradecard_backed.replace(
        'Source: catalyst-backed + scanner-confirmed', ''
    ):
        return _fail('must not overwrite catalyst-backed with scanner-confirmed')

    explain_backed = _format_tradecard(backed_card, explain=True, freshness=freshness)
    if 'Source: catalyst-backed + scanner-confirmed' not in explain_backed:
        return _fail('/tradecard explain must include catalyst-backed source label')

    with patch(
        'backend.trading.unified_live_priority_engine.decision_source_label',
        return_value='Source: scanner-confirmed',
    ):
        stale_lookup = _format_tradecard(backed_card, freshness=freshness)
    if 'Source: catalyst-backed + scanner-confirmed' not in stale_lookup:
        return _fail('engine source_label must win over recomputed scanner-confirmed')

    payload = {
        'decision': 'WATCH_FOR_ENTRY',
        'top_pick': {
            'ticker': 'SUNDRMFAST',
            'action': 'WATCH_FOR_ENTRY',
            'unified_score': 75,
            'why': [],
            'risk': [],
        },
        'ranked_candidates': [],
    }
    with patch(
        'backend.trading.unified_live_priority_engine.decision_source_label',
        return_value='Source: scanner-confirmed',
    ), patch('backend.trading.unified_live_priority_engine._is_postmarket_mode', return_value=False):
        today = format_today_unified(payload)
    if 'Source: scanner-confirmed' not in today:
        return _fail('/today must include source label')

    with patch(
        'backend.trading.unified_live_priority_engine.decision_source_label',
        return_value='Source: catalyst-backed + scanner-confirmed',
    ), patch('backend.trading.unified_live_priority_engine._is_postmarket_mode', return_value=False):
        backed_today = format_today_unified(payload)
    if 'Source: catalyst-backed + scanner-confirmed' not in backed_today:
        return _fail('/today catalyst-backed label must render when returned by engine')

    print('TRADECARD_SOURCE_LABEL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
