#!/usr/bin/env python3
"""
Smoke test for scripts/audit_price_coverage.py (read-only).

Usage:
  python scripts/test_price_coverage_audit.py

Prints exactly PRICE_COVERAGE_AUDIT_OK on success; exits 1 on failure.
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
    print(f'PRICE_COVERAGE_AUDIT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_db import get_connection, get_market_memory_stats

    stats_before = get_market_memory_stats()

    try:
        from scripts.audit_price_coverage import (
            build_ticker_variants,
            classify_prediction,
            run_audit,
        )
    except ImportError as exc:
        return _fail(f'import audit_price_coverage failed: {exc}')

    variants = build_ticker_variants('reliance-eq')
    if not variants or 'RELIANCE' not in variants:
        return _fail('build_ticker_variants did not normalize RELIANCE')

    synthetic_market = {
        'last_updated': '2026-01-10T12:00:00+00:00',
        'prices': {
            'RELIANCE': {'price': 100.0},
        },
    }
    synthetic_prediction = {
        'prediction_id': '__TEST_PRICE_COVERAGE__',
        'ticker': 'RELIANCE',
        'direction': 'BULLISH',
        'raw_payload': {
            'entry_price': 100.0,
            'target_price': 115.0,
            'stop_loss': 95.0,
        },
    }
    record = classify_prediction(synthetic_prediction, synthetic_market)
    if record.get('classification') != 'eligible_unresolved':
        return _fail(
            f'classify_prediction expected eligible_unresolved, got {record.get("classification")}',
        )

    try:
        summary = run_audit(limit=5, verbose=False)
    except RuntimeError as exc:
        return _fail(f'run_audit failed: {exc}')

    if not isinstance(summary, dict):
        return _fail('run_audit did not return a dict')
    if 'predictions_checked' not in summary or 'counts' not in summary:
        return _fail('run_audit summary missing required keys')
    if not isinstance(summary.get('records'), list):
        return _fail('run_audit records is not a list')

    stats_after = get_market_memory_stats()
    for key in ('predictions', 'broker_predictions', 'outcomes', 'market_context_snapshots'):
        if stats_before.get(key) != stats_after.get(key):
            return _fail(
                f'table count changed for {key}: '
                f'{stats_before.get(key)} -> {stats_after.get(key)}',
            )

    conn = get_connection()
    try:
        conn.execute('PRAGMA query_only = ON')
        conn.execute('SELECT COUNT(*) FROM predictions').fetchone()
    finally:
        conn.close()

    print('PRICE_COVERAGE_AUDIT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
