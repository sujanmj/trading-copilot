#!/usr/bin/env python3
"""
Smoke test for batch market memory shadow advisor report.

Usage:
  python scripts/test_market_memory_advisor_batch.py

Prints exactly MARKET_MEMORY_ADVISOR_BATCH_OK on success; exits 1 on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'MARKET_MEMORY_ADVISOR_BATCH_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.market_memory_advisor import get_advisor_batch_report
    from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    stats_before = get_market_memory_stats()
    report = get_advisor_batch_report(limit=10)

    stats_after = get_market_memory_stats()
    for key in ('predictions', 'outcomes'):
        if stats_before.get(key) != stats_after.get(key):
            return _fail(
                f'{key} count changed: before={stats_before.get(key)} after={stats_after.get(key)}'
            )

    if report.get('shadow_mode') is not True:
        return _fail('shadow_mode must be true')

    if not report.get('ok'):
        return _fail('get_advisor_batch_report returned ok=False')

    checked = int(report.get('checked') or 0)
    if checked < 0:
        return _fail('checked must be non-negative')

    for key in ('boost', 'neutral', 'caution', 'avoid_candidate'):
        if key not in report:
            return _fail(f'missing summary key: {key}')

    total_advice = sum(int(report.get(key) or 0) for key in ('boost', 'neutral', 'caution', 'avoid_candidate'))
    if total_advice != checked:
        return _fail(f'advice counts sum {total_advice} != checked {checked}')

    rows = report.get('rows') or []
    if len(rows) != checked:
        return _fail(f'rows length {len(rows)} != checked {checked}')

    if rows:
        required = (
            'prediction_id',
            'ticker',
            'direction',
            'confidence_label',
            'signal_type',
            'horizon',
            'broker_consensus',
            'advice',
            'learning_score',
            'warnings',
        )
        for field in required:
            if field not in rows[0]:
                return _fail(f'missing row field: {field}')

    print('MARKET_MEMORY_ADVISOR_BATCH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
