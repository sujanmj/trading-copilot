#!/usr/bin/env python3
"""Stage 50Z hotfix — active TRACKING /tradecard appends sample and updates outcome."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
from _tradecard_journal_test_helpers import isolated_tradecard_store, sample_valid_card


def _fail(msg: str) -> int:
    print(f'TRADECARD_TRACKING_UPDATES_OUTCOME_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.tradecard_journal import (
        OUTCOME_T1_HIT,
        _read_journal,
        load_path_samples,
        persist_tradecard_generation,
    )

    original = sample_valid_card(
        ticker='BATAINDIA',
        current_price=760.9,
        entry_zone='758.00–762.00',
        stop_loss=755.0,
        target_1=768.0,
        target_2=775.0,
    )
    rolled = {
        **original,
        'current_price': 757.0,
        'entry_zone': '755.00–759.00',
    }
    market_data = {
        'prices': {
            'BATAINDIA': {
                'price': 769.5,
                'high': 770.0,
                'low': 759.0,
            },
        },
    }

    with isolated_tradecard_store(), \
         patch('backend.trading.tradecard_journal._today', return_value='2026-06-19'):
        row = persist_tradecard_generation(original)
        if not row:
            return _fail('initial BATAINDIA card must persist')

        with patch('backend.trading.trade_card_engine.get_trade_card', return_value=rolled), \
             patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
             patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('BATAINDIA', 'VALID_ENTRY')), \
             patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''), \
             patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False), \
             patch('backend.storage.market_memory_outcomes.load_latest_market_data', return_value=market_data):
            text = format_tradecard_telegram(explain=False, freshness_meta={'quote_refreshed_now': True})

        if 'ACTIVE CARD EXISTS' not in text.upper():
            return _fail('/tradecard must show ACTIVE CARD EXISTS tracking view')

        samples = load_path_samples(str(row.get('id')))
        if not samples:
            return _fail('tracking /tradecard must append path sample')

        updated_rows = [r for r in _read_journal() if str(r.get('id')) == str(row.get('id'))]
        updated = updated_rows[0] if updated_rows else {}
        if str(updated.get('outcome_status') or '') != OUTCOME_T1_HIT:
            return _fail(f'tracking must resolve T1 when price >= T1, got {updated.get("outcome_status")!r}')

    print('TRADECARD_TRACKING_UPDATES_OUTCOME_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
