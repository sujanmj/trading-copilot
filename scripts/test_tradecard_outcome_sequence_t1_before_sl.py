#!/usr/bin/env python3
"""Stage 50Z — outcome sequencing resolves T1 before later SL (NILKAMAL)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
from _tradecard_journal_test_helpers import isolated_tradecard_journal, nilkamal_levels, sample_valid_card


def _fail(msg: str) -> int:
    print(f'TRADECARD_OUTCOME_SEQUENCE_T1_BEFORE_SL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.tradecard_journal import (
        OUTCOME_T1_HIT,
        OUTCOME_T2_HIT,
        apply_path_to_journal_record,
        persist_tradecard_generation,
        resolve_outcome_sequence,
    )

    entry_low, entry_high, stop, t1, t2 = nilkamal_levels()
    path = [
        {'ts': '2026-06-19T10:05:00+05:30', 'price': 1345.0, 'high': 1348.0, 'low': 1343.0},
        {'ts': '2026-06-19T10:20:00+05:30', 'price': 1360.0, 'high': 1360.0, 'low': 1345.0},
        {'ts': '2026-06-19T10:40:00+05:30', 'price': 1330.0, 'high': 1335.0, 'low': 1330.0},
    ]
    resolved = resolve_outcome_sequence(
        entry_low=entry_low,
        entry_high=entry_high,
        stop=stop,
        t1=t1,
        t2=t2,
        path=path,
        signal_time='2026-06-19T10:00:00+05:30',
    )
    outcome = str(resolved.get('outcome_status') or '')
    if outcome not in (OUTCOME_T1_HIT, OUTCOME_T2_HIT):
        return _fail(f'expected T1/T2 before SL, got {outcome!r}')

    with isolated_tradecard_journal():
        record = persist_tradecard_generation(sample_valid_card())
        if not record:
            return _fail('NILKAMAL VALID_ENTRY must persist')
        updated = apply_path_to_journal_record(record, path)
        if str(updated.get('outcome_status')) not in (OUTCOME_T1_HIT, OUTCOME_T2_HIT):
            return _fail(f'journal row must be T1/T2, got {updated.get("outcome_status")!r}')

    print('TRADECARD_OUTCOME_SEQUENCE_T1_BEFORE_SL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
