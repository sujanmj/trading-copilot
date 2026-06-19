#!/usr/bin/env python3
"""Stage 50Z — active lock blocks duplicate VALID_ENTRY for same ticker."""

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
    print(f'TRADECARD_ACTIVE_LOCK_PREVENTS_DUPLICATE_SAME_TICKER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.tradecard_journal import can_issue_new_valid_entry, persist_tradecard_generation

    card = sample_valid_card()
    with isolated_tradecard_journal():
        first = persist_tradecard_generation(card)
        if not first:
            return _fail('first VALID_ENTRY must persist')
        ok, active = can_issue_new_valid_entry('NILKAMAL', card=card)
        if ok or not active:
            return _fail('active lock must block second VALID_ENTRY')
        second = persist_tradecard_generation(card)
        if second is not None:
            return _fail('duplicate VALID_ENTRY must not append to journal')

        with patch('backend.trading.trade_card_engine.get_trade_card', return_value=card), \
             patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
             patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('NILKAMAL', 'VALID_ENTRY')), \
             patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''), \
             patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False):
            text = format_tradecard_telegram(explain=False, freshness_meta={'quote_refreshed_now': True})

        if 'ACTIVE CARD EXISTS' not in text.upper():
            return _fail('/tradecard must show ACTIVE CARD EXISTS when lock active')

    print('TRADECARD_ACTIVE_LOCK_PREVENTS_DUPLICATE_SAME_TICKER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
