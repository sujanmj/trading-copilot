#!/usr/bin/env python3
"""Stage 50Z addendum — no rolling duplicate VALID_ENTRY when active card exists."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
from _tradecard_journal_test_helpers import isolated_tradecard_journal, sample_valid_card


def _fail(msg: str) -> int:
    print(f'TRADECARD_NO_ROLLING_DOWN_DUPLICATE_ENTRIES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.tradecard_journal import _read_journal, persist_tradecard_generation

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
        'stop_loss': 752.0,
        'target_1': 765.0,
        'target_2': 772.0,
        'reason': 'lower price should not spawn new card',
    }

    with isolated_tradecard_journal():
        first = persist_tradecard_generation(original)
        if not first:
            return _fail('initial BATAINDIA VALID_ENTRY must persist')

        with patch('backend.trading.trade_card_engine.get_trade_card', return_value=rolled), \
             patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
             patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('BATAINDIA', 'VALID_ENTRY')), \
             patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''), \
             patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False):
            text = format_tradecard_telegram(explain=False, freshness_meta={'quote_refreshed_now': True})

        if 'ACTIVE CARD EXISTS' not in text.upper():
            return _fail('lower price /tradecard must show ACTIVE CARD EXISTS')
        if '758' not in text and '758.00' not in text:
            return _fail('active card must keep original entry zone, not rolled-down levels')
        if '755.00–759.00' in text:
            return _fail('must not show rolled-down entry zone as new VALID_ENTRY')

        records = _read_journal()
        valid_entries = [
            r for r in records
            if r.get('ticker') == 'BATAINDIA' and r.get('status') == 'VALID_ENTRY'
        ]
        if len(valid_entries) != 1:
            return _fail('journal must contain exactly one BATAINDIA VALID_ENTRY')

    print('TRADECARD_NO_ROLLING_DOWN_DUPLICATE_ENTRIES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
