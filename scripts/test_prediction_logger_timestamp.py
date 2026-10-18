#!/usr/bin/env python3
"""Regression checks that prediction capture preserves real decision time."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analyzers.prediction_logger import _source_decision_timestamp
from backend.storage.market_memory_capture import normalize_prediction_payload


def main() -> int:
    aware = _source_decision_timestamp(
        {'timestamp': '2026-10-18T09:12:34+05:30'}
    )
    if aware != '2026-10-18T09:12:34+05:30':
        raise AssertionError(f'aware decision time changed: {aware!r}')

    naive = _source_decision_timestamp(
        {'timestamp': '2026-10-18T09:12:34'}
    )
    if naive != '2026-10-18T09:12:34+05:30':
        raise AssertionError(f'naive decision time not normalized to IST: {naive!r}')

    if _source_decision_timestamp({'timestamp': '2026-10-18'}) is not None:
        raise AssertionError('date-only input was promoted to an instant')
    if _source_decision_timestamp({'timestamp': 'not-a-time'}) is not None:
        raise AssertionError('invalid input was accepted as a decision time')

    captured = normalize_prediction_payload(
        {
            'ticker': 'TESTCO',
            'timestamp': aware,
            'decision_timestamp_source': 'unified_intelligence_timestamp',
            'recommendation': 'BUY',
        },
        source_hint='prediction_logger_test',
    )
    if captured is None or captured.get('timestamp') != aware:
        raise AssertionError('canonical capture did not preserve decision instant')
    stack = captured.get('signal_stack') or {}
    if stack.get('decision_timestamp_source') != 'unified_intelligence_timestamp':
        raise AssertionError('timestamp provenance missing from captured signal stack')

    print('PREDICTION_LOGGER_TIMESTAMP_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
