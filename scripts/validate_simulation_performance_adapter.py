#!/usr/bin/env python3
"""
Validate simulation performance adapter module.

Usage:
  python scripts/validate_simulation_performance_adapter.py

Prints exactly SIMULATION_PERFORMANCE_ADAPTER_OK on success.
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
    print(f'SIMULATION_PERFORMANCE_ADAPTER_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics import simulation_performance_adapter as adapter
    from backend.analytics.simulation_performance_adapter import (
        SIMULATION_ADJUSTMENT_CAP,
        infer_candidate_strategy,
        score_simulation_evidence,
    )

    for name in (
        'get_simulation_summary',
        'get_strategy_performance',
        'get_ticker_simulation_performance',
        'infer_candidate_strategy',
        'score_simulation_evidence',
    ):
        if not callable(getattr(adapter, name, None)):
            return _fail(f'missing function: {name}')

    momentum = infer_candidate_strategy({'signal_type': 'breakout', 'direction': 'BUY'})
    if momentum.get('inferred_strategy') != 'momentum_breakout_20':
        return _fail(f'expected momentum_breakout_20, got {momentum.get("inferred_strategy")}')

    bearish = infer_candidate_strategy({'direction': 'BEARISH', 'category': 'breakdown'})
    if bearish.get('inferred_strategy') != 'bearish_breakdown_20':
        return _fail(f'expected bearish_breakdown_20, got {bearish.get("inferred_strategy")}')

    unknown = infer_candidate_strategy({'ticker': 'TEST', 'direction': 'NEUTRAL'})
    if unknown.get('inferred_strategy') != 'UNKNOWN':
        return _fail('expected UNKNOWN for neutral candidate')

    evidence = score_simulation_evidence({'ticker': 'ZZZNOSIM', 'signal_type': 'breakout'})
    for key in (
        'ok',
        'ticker',
        'inferred_strategy',
        'strategy_sample',
        'strategy_win_rate',
        'strategy_expectancy_pct',
        'ticker_sample',
        'ticker_win_rate',
        'confidence_adjustment',
        'warnings',
        'reasons',
    ):
        if key not in evidence:
            return _fail(f'score_simulation_evidence missing key: {key}')

    adj = int(evidence.get('confidence_adjustment') or 0)
    if abs(adj) > SIMULATION_ADJUSTMENT_CAP:
        return _fail(f'adjustment {adj} exceeds cap {SIMULATION_ADJUSTMENT_CAP}')

    summary = adapter.get_simulation_summary()
    if summary.get('ok') is not True:
        return _fail('get_simulation_summary ok != true')
    if 'stats' not in summary:
        return _fail('get_simulation_summary missing stats')

    from backend.storage.historical_market_store import get_connection, init_db

    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT strategy) AS cnt
            FROM historical_strategy_performance
            """
        ).fetchone()
        db_strategy_count = int(row['cnt']) if row else 0
    finally:
        conn.close()

    adapter_count = int(summary.get('strategy_count') or 0)
    if adapter_count < db_strategy_count:
        return _fail(
            f'adapter strategy_count={adapter_count} lower than DB={db_strategy_count}',
        )

    perf = adapter.get_strategy_performance()
    adapter_names = {
        str(row.get('strategy') or '')
        for row in (perf.get('rows') or [])
        if row.get('strategy')
    }
    if db_strategy_count > 0 and len(adapter_names) < db_strategy_count:
        return _fail('get_strategy_performance missing DB-backed strategies')

    print('SIMULATION_PERFORMANCE_ADAPTER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
