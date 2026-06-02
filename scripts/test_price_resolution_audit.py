#!/usr/bin/env python3
"""
Smoke test for scripts/audit_price_resolution_candidates.py (read-only).

Usage:
  python scripts/test_price_resolution_audit.py

Prints exactly PRICE_RESOLUTION_AUDIT_OK on success; exits 1 on failure.
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
    print(f'PRICE_RESOLUTION_AUDIT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_db import get_connection, get_market_memory_stats

    stats_before = get_market_memory_stats()

    try:
        from scripts.audit_price_resolution_candidates import (
            build_candidate_row,
            classify_prediction_skip,
            run_audit,
        )
    except ImportError as exc:
        return _fail(f'import audit_price_resolution_candidates failed: {exc}')

    synthetic_market = {
        'last_updated': '2026-01-10T12:00:00+00:00',
        'prices': {
            'RELIANCE': {
                'price': 120.0,
                'source': 'test',
                'validated_at': '2026-01-10T12:00:00+00:00',
            },
        },
    }
    synthetic_prediction = {
        'prediction_id': '__TEST_PRICE_RESOLUTION_AUDIT__',
        'ticker': 'RELIANCE',
        'direction': 'BULLISH',
        'timestamp': '2026-01-01T00:00:00+00:00',
        'confidence': 0.7,
        'raw_payload': {
            'entry_price': 100.0,
            'target_price': 115.0,
            'stop_loss': 95.0,
        },
    }

    skip_reason = classify_prediction_skip(synthetic_prediction, synthetic_market)
    if skip_reason != 'would_resolve':
        return _fail(
            f'classify_prediction_skip expected would_resolve, got {skip_reason}',
        )

    row = build_candidate_row(synthetic_prediction, synthetic_market)
    if row is None:
        return _fail('build_candidate_row returned None for synthetic target hit')
    if row.get('would_result') != 'WIN':
        return _fail(f'expected WIN, got {row.get("would_result")}')
    if row.get('would_expiry_result') != 'TARGET_HIT_BY_PRICE':
        return _fail(
            f'expected TARGET_HIT_BY_PRICE, got {row.get("would_expiry_result")}',
        )
    if row.get('sanity_status') != 'ok':
        return _fail(f'expected sanity_status ok, got {row.get("sanity_status")}')

    try:
        summary = run_audit(limit=5, market_data=synthetic_market, allow_stale=True)
    except RuntimeError as exc:
        return _fail(f'run_audit failed: {exc}')

    if not isinstance(summary, dict):
        return _fail('run_audit did not return a dict')
    for key in ('checked', 'would_resolve', 'rows'):
        if key not in summary:
            return _fail(f'run_audit summary missing key: {key}')
    if not isinstance(summary.get('rows'), list):
        return _fail('run_audit rows is not a list')

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

    print('PRICE_RESOLUTION_AUDIT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
