#!/usr/bin/env python3
"""Stage 50Z — daily review includes tradecard outcome counts."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
from _tradecard_journal_test_helpers import isolated_tradecard_journal, sample_sutlejtex_card, sample_valid_card


def _fail(msg: str) -> int:
    print(f'TRADECARD_DAILY_REVIEW_COUNTS_OUTCOMES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.eod_outcome_scoring import _tradecard_review_block
    from backend.trading.tradecard_journal import (
        OUTCOME_SL_HIT,
        OUTCOME_T2_HIT,
        apply_path_to_journal_record,
        format_tradecard_review_section,
        persist_tradecard_generation,
        update_journal_record,
    )

    t2_path = [
        {'ts': '2026-06-19T10:05:00+05:30', 'price': 1345.0, 'high': 1348.0, 'low': 1343.0},
        {'ts': '2026-06-19T10:20:00+05:30', 'price': 1370.0, 'high': 1370.0, 'low': 1345.0},
    ]
    sl_path = [
        {'ts': '2026-06-19T10:20:00+05:30', 'price': 52.0, 'high': 52.4, 'low': 51.6},
        {'ts': '2026-06-19T10:35:00+05:30', 'price': 49.5, 'high': 51.0, 'low': 49.5},
    ]

    with isolated_tradecard_journal():
        nil_row = persist_tradecard_generation(sample_valid_card())
        sut_row = persist_tradecard_generation(sample_sutlejtex_card())
        if not nil_row or not sut_row:
            return _fail('fixtures must persist')
        apply_path_to_journal_record(nil_row, t2_path)
        apply_path_to_journal_record(sut_row, sl_path)
        persist_tradecard_generation(sample_valid_card(status='NO_TRADE', ticker='KPIL'))

        section = format_tradecard_review_section(session_date='2026-06-19')
        for marker in ('<b>Tradecards:</b>', 'Generated:', 'Filled:', 'T1:', 'T2:', 'SL:'):
            if marker not in section:
                return _fail(f'review section missing {marker!r}')

        summary = {'date': '2026-06-19'}
        block = _tradecard_review_block(summary)
        if 'Generated:' not in block or 'SL:' not in block:
            return _fail('EOD review block must include tradecard counts')

    with isolated_tradecard_journal(), \
         patch('backend.trading.tradecard_journal._today', return_value='2026-06-19'):
        nil_row = persist_tradecard_generation(sample_valid_card())
        update_journal_record(
            str(nil_row.get('id')),
            {'outcome_status': OUTCOME_T2_HIT, 'outcome_price': 1367.19, 'filled_at': '2026-06-19T10:20:00+05:30'},
        )
        sut_row = persist_tradecard_generation(sample_sutlejtex_card())
        update_journal_record(
            str(sut_row.get('id')),
            {'outcome_status': OUTCOME_SL_HIT, 'outcome_price': 50.0, 'filled_at': '2026-06-19T10:35:00+05:30'},
        )
        from backend.trading.tradecard_journal import summarize_today_outcomes

        counts = (summarize_today_outcomes(session_date='2026-06-19').get('counts') or {})
        if counts.get('T2', 0) < 1 or counts.get('SL', 0) < 1:
            return _fail(f'expected T2 and SL counts, got {counts!r}')

    print('TRADECARD_DAILY_REVIEW_COUNTS_OUTCOMES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
