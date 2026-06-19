#!/usr/bin/env python3
"""Stage 50Z — outcome sequencing resolves SL before T1 (SUTLEJTEX)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
from _tradecard_journal_test_helpers import isolated_tradecard_journal, sample_sutlejtex_card, sutlejtex_levels


def _fail(msg: str) -> int:
    print(f'TRADECARD_OUTCOME_SEQUENCE_SL_BEFORE_T1_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.tradecard_journal import (
        OUTCOME_SL_HIT,
        apply_path_to_journal_record,
        persist_tradecard_generation,
        resolve_outcome_sequence,
    )

    entry_low, entry_high, stop, t1, t2 = sutlejtex_levels()
    path = [
        {'ts': '2026-06-19T10:20:00+05:30', 'price': 52.0, 'high': 52.4, 'low': 51.6},
        {'ts': '2026-06-19T10:35:00+05:30', 'price': 49.5, 'high': 51.0, 'low': 49.5},
        {'ts': '2026-06-19T11:00:00+05:30', 'price': 55.0, 'high': 55.0, 'low': 54.5},
    ]
    resolved = resolve_outcome_sequence(
        entry_low=entry_low,
        entry_high=entry_high,
        stop=stop,
        t1=t1,
        t2=t2,
        path=path,
        signal_time='2026-06-19T10:15:00+05:30',
    )
    if str(resolved.get('outcome_status')) != OUTCOME_SL_HIT:
        return _fail(f'expected SL_HIT, got {resolved.get("outcome_status")!r}')

    with isolated_tradecard_journal():
        record = persist_tradecard_generation(sample_sutlejtex_card())
        if not record:
            return _fail('SUTLEJTEX VALID_ENTRY must persist')
        updated = apply_path_to_journal_record(record, path)
        if str(updated.get('outcome_status')) != OUTCOME_SL_HIT:
            return _fail(f'journal row must be SL_HIT, got {updated.get("outcome_status")!r}')

    print('TRADECARD_OUTCOME_SEQUENCE_SL_BEFORE_T1_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
