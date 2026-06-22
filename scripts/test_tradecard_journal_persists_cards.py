#!/usr/bin/env python3
"""Stage 50Z — tradecard journal persists generated cards."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
from _tradecard_journal_test_helpers import isolated_tradecard_journal, sample_valid_card


def _fail(msg: str) -> int:
    print(f'TRADECARD_JOURNAL_PERSISTS_CARDS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.tradecard_journal import persist_tradecard_generation

    with isolated_tradecard_journal() as journal:
        no_trade = sample_valid_card(status='NO_TRADE', ticker='KPIL')
        row = persist_tradecard_generation(no_trade)
        if row is not None:
            return _fail('NO_TRADE / NO ACTIVE ENTRY must not persist to journal')
        valid = sample_valid_card()
        saved = persist_tradecard_generation(valid)
        if not saved or str(saved.get('outcome_status')) != 'PENDING':
            return _fail('VALID_ENTRY must persist with PENDING outcome')

        fake_card = sample_valid_card(ticker='NILKAMAL')
        with patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card), \
             patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
             patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('NILKAMAL', 'VALID_ENTRY')), \
             patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''), \
             patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False):
            text = format_tradecard_telegram(explain=False, freshness_meta={'quote_refreshed_now': True})

        if 'TRADE CARD' not in text.upper():
            return _fail('/tradecard format must return trade card')
        lines = [ln for ln in journal.read_text(encoding='utf-8').splitlines() if ln.strip()]
        if len(lines) < 1:
            return _fail('journal must contain VALID_ENTRY row after /tradecard')
        rows = [json.loads(ln) for ln in lines]
        valid_rows = [r for r in rows if str(r.get('status') or '').upper() == 'VALID_ENTRY']
        if len(valid_rows) < 1:
            return _fail('expected at least one VALID_ENTRY row in journal')

    print('TRADECARD_JOURNAL_PERSISTS_CARDS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
