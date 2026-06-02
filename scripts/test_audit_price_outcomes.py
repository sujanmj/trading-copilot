#!/usr/bin/env python3
"""
Smoke test for scripts/audit_price_outcomes.py (read-only).

Usage:
  python scripts/test_audit_price_outcomes.py

Prints exactly PRICE_OUTCOME_AUDIT_OK on success; exits 1 on failure.
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
    print(f'PRICE_OUTCOME_AUDIT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_db import get_connection, get_market_memory_stats

    stats_before = get_market_memory_stats()

    try:
        from scripts.audit_price_outcomes import run_audit
    except ImportError as exc:
        return _fail(f'import audit_price_outcomes failed: {exc}')

    summary = run_audit(verbose=False)

    if not isinstance(summary, dict):
        return _fail('run_audit did not return a dict')
    if 'outcomes_checked' not in summary or 'anomaly_ids' not in summary:
        return _fail('run_audit summary missing required keys')
    if not isinstance(summary['rows'], list):
        return _fail('run_audit rows is not a list')

    stats_after = get_market_memory_stats()
    for key in ('predictions', 'broker_predictions', 'outcomes', 'market_context_snapshots'):
        if stats_before.get(key) != stats_after.get(key):
            return _fail(f'table count changed for {key}: {stats_before.get(key)} -> {stats_after.get(key)}')

    conn = get_connection()
    try:
        conn.execute('PRAGMA query_only = ON')
        conn.execute('SELECT COUNT(*) FROM outcomes').fetchone()
    finally:
        conn.close()

    print('PRICE_OUTCOME_AUDIT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
