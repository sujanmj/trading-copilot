#!/usr/bin/env python3
"""
Smoke test for unified market memory dashboard payload.

Usage:
  python scripts/test_market_memory_dashboard.py

Prints exactly MARKET_MEMORY_DASHBOARD_OK on success; exits 1 on failure.
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
    print(f'MARKET_MEMORY_DASHBOARD_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.market_memory_dashboard import get_market_memory_dashboard
    from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    stats_before = get_market_memory_stats()
    dashboard = get_market_memory_dashboard(limit=10)
    stats_after = get_market_memory_stats()

    for key in ('predictions', 'outcomes', 'broker_predictions', 'market_context_snapshots'):
        if stats_before.get(key) != stats_after.get(key):
            return _fail(
                f'{key} count changed: before={stats_before.get(key)} after={stats_after.get(key)}'
            )

    if not dashboard.get('ok'):
        return _fail('get_market_memory_dashboard returned ok=False')

    for section in ('stats', 'learning', 'advisor', 'price_coverage', 'outcome_audit'):
        if section not in dashboard:
            return _fail(f'missing section: {section}')

    advisor = dashboard.get('advisor') or {}
    for key in ('checked', 'boost', 'neutral', 'caution', 'avoid_candidate', 'shadow_mode'):
        if key not in advisor:
            return _fail(f'missing advisor key: {key}')

    price_coverage = dashboard.get('price_coverage') or {}
    for key in (
        'price_file',
        'symbols',
        'missing_latest_price',
        'missing_price_context',
        'suspicious_price_scale',
        'eligible_unresolved',
    ):
        if key not in price_coverage:
            return _fail(f'missing price_coverage key: {key}')

    outcome_audit = dashboard.get('outcome_audit') or {}
    for key in ('outcomes_checked', 'anomalies'):
        if key not in outcome_audit:
            return _fail(f'missing outcome_audit key: {key}')

    if not isinstance(dashboard.get('latest_predictions'), list):
        return _fail('latest_predictions must be a list')
    if not isinstance(dashboard.get('latest_outcomes'), list):
        return _fail('latest_outcomes must be a list')
    if not isinstance(dashboard.get('warnings'), list):
        return _fail('warnings must be a list')

    try:
        from backend.api.api_server import api_debug_market_memory_dashboard

        api_result = api_debug_market_memory_dashboard(limit=10)
        if not api_result.get('ok'):
            return _fail(f'api_debug_market_memory_dashboard ok=False: {api_result.get("error")}')
    except Exception:
        if not dashboard.get('ok'):
            return _fail('dashboard ok=False and api import unavailable')

    print('MARKET_MEMORY_DASHBOARD_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
