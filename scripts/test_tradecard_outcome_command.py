#!/usr/bin/env python3
"""Stage 50Z — /tradecard journal and /tradecard outcome commands."""

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
    print(f'TRADECARD_OUTCOME_COMMAND_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_tradecard_only
    from backend.trading.tradecard_journal import (
        OUTCOME_AMBIGUOUS,
        OUTCOME_SL_HIT,
        OUTCOME_T2_HIT,
        apply_path_to_journal_record,
        persist_tradecard_generation,
    )

    t2_path = [
        {'ts': '2026-06-19T10:05:00+05:30', 'price': 1345.0, 'high': 1348.0, 'low': 1343.0},
        {'ts': '2026-06-19T10:20:00+05:30', 'price': 1370.0, 'high': 1370.0, 'low': 1345.0},
    ]
    ambiguous_path = [
        {'ts': '2026-06-19T10:25:00+05:30', 'price': 52.0, 'high': 55.0, 'low': 49.5},
    ]

    with isolated_tradecard_journal(), \
         patch('backend.trading.tradecard_journal._today', return_value='2026-06-19'):
        nil_row = persist_tradecard_generation(sample_valid_card())
        apply_path_to_journal_record(nil_row, t2_path)
        sut_row = persist_tradecard_generation(sample_sutlejtex_card())
        apply_path_to_journal_record(sut_row, ambiguous_path)

        journal = run_tradecard_only('journal', chat_id='outcome-cmd')
        journal_text = str(journal.get('text') or '')
        if 'Tradecard Journal' not in journal_text:
            return _fail('/tradecard journal must return journal header')
        if 'NILKAMAL' not in journal_text or 'SUTLEJTEX' not in journal_text:
            return _fail('journal must list NILKAMAL and SUTLEJTEX')
        if OUTCOME_T2_HIT not in journal_text:
            return _fail('journal must show NILKAMAL T2 outcome')
        if OUTCOME_AMBIGUOUS not in journal_text:
            return _fail('journal must show SUTLEJTEX AMBIGUOUS outcome')

        outcome = run_tradecard_only('outcome', chat_id='outcome-cmd')
        outcome_text = str(outcome.get('text') or '')
        if outcome_text != journal_text:
            return _fail('/tradecard outcome must match journal output')
        if OUTCOME_SL_HIT not in outcome_text:
            return _fail('outcome view must show conservative SL label for ambiguous row')

    print('TRADECARD_OUTCOME_COMMAND_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
