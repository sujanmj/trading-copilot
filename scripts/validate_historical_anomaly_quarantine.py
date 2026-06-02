#!/usr/bin/env python3
"""
Validate historical anomaly quarantine table, audit writes, and replay safety.

Usage:
  python scripts/validate_historical_anomaly_quarantine.py

Prints HISTORICAL_ANOMALY_QUARANTINE_VALIDATE_OK on success.
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
    print(f'HISTORICAL_ANOMALY_QUARANTINE_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.historical_market_store import (
        get_active_anomalies,
        get_connection,
        get_historical_db_path,
        get_stats,
        init_db,
    )
    from backend.storage.historical_outcome_replay import replay_prediction_outcomes
    from backend.storage.market_memory_db import (
        get_market_memory_path,
        get_market_memory_stats,
        init_market_memory_db,
    )

    if not init_db():
        return _fail('init_db failed')

    db_path = get_historical_db_path()
    if not db_path.exists():
        return _fail(f'historical database missing: {db_path}')

    conn = get_connection()
    try:
        tables = {
            row['name']
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if 'historical_price_anomalies' not in tables:
            return _fail('missing table: historical_price_anomalies')
    finally:
        conn.close()

    stats = get_stats()
    active = int(stats.get('historical_price_anomalies_active') or 0)
    if active < 1:
        return _fail(
            'no active anomalies in quarantine '
            '(run audit_historical_price_quality.py --write-anomalies first)'
        )

    fake_rows = int(stats.get('fake_prices_rows') or 0)
    if fake_rows != 0:
        return _fail(f'fake_prices_rows={fake_rows}, expected 0')

    if not init_market_memory_db():
        return _fail('canonical init_market_memory_db failed')

    canonical_path = get_market_memory_path()
    if not canonical_path.exists():
        return _fail(f'canonical DB missing: {canonical_path}')

    canonical_stats = get_market_memory_stats()
    if not canonical_stats.get('db_exists'):
        return _fail('canonical db_exists is False')

    anomalies = get_active_anomalies()
    exclude_count = sum(
        1 for row in anomalies if row.get('severity') == 'exclude_from_simulation'
    )
    print(f'[HIST_ANOMALY_VALIDATE] active={active}')
    print(f'[HIST_ANOMALY_VALIDATE] exclude_from_simulation={exclude_count}')

    replay_summary = replay_prediction_outcomes(dry_run=True, limit=5)
    if replay_summary.get('errors', 0) > 0:
        return _fail('replay dry-run reported errors')

    print(f'[HIST_ANOMALY_VALIDATE] replay_checked={replay_summary.get("predictions_checked", 0)}')
    print(f'[HIST_ANOMALY_VALIDATE] anomaly_excluded_dates={replay_summary.get("anomaly_excluded_dates", 0)}')

    print('HISTORICAL_ANOMALY_QUARANTINE_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
