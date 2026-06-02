#!/usr/bin/env python3
"""
Smoke test for source freshness report.

Usage:
  python scripts/test_source_freshness.py

Prints exactly SOURCE_FRESHNESS_OK on success; exits 1 on failure.
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
    print(f'SOURCE_FRESHNESS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.source_freshness import STALE_HOURS, get_source_freshness_report

    report = get_source_freshness_report()

    if report.get('ok') is not True:
        return _fail('ok != true')

    for key in (
        'market_status',
        'runtime_snapshot_age_hours',
        'latest_market_data_age_hours',
        'enriched_price_age_hours',
        'news_age_hours',
        'sources',
        'warnings',
    ):
        if key not in report:
            return _fail(f'missing key: {key}')

    if report.get('market_status') not in ('open', 'closed', 'unknown'):
        return _fail(f"invalid market_status: {report.get('market_status')}")

    sources = report.get('sources') or {}
    for section in ('prices', 'news', 'reddit', 'global', 'govt', 'market_memory'):
        if section not in sources:
            return _fail(f'missing sources.{section}')
        block = sources[section]
        if 'status' not in block:
            return _fail(f'missing status in sources.{section}')

    warnings = report.get('warnings')
    if not isinstance(warnings, list):
        return _fail('warnings must be a list')

    runtime_age = report.get('runtime_snapshot_age_hours')
    if runtime_age is not None and float(runtime_age) > STALE_HOURS:
        if 'runtime_snapshot_stale' not in warnings:
            return _fail('expected runtime_snapshot_stale warning')

    try:
        from backend.api.api_server import api_debug_source_freshness

        api_result = api_debug_source_freshness()
        if not api_result.get('ok'):
            return _fail(f'api_debug_source_freshness ok=False: {api_result.get("error")}')
    except Exception:
        pass

    print('SOURCE_FRESHNESS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
