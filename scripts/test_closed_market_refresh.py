#!/usr/bin/env python3
"""
Test closed-market intelligence refresh (Stage 43C) with mocks.

Prints exactly CLOSED_MARKET_REFRESH_TEST_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'CLOSED_MARKET_REFRESH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from scripts.refresh_closed_market_intelligence import run_closed_market_refresh

    with patch('scripts.refresh_closed_market_intelligence._router_mode', return_value=('RESEARCH_MODE', True)):
        dry = run_closed_market_refresh(dry_run=True)
        if dry.get('ok') is not True:
            return _fail('dry_run expected ok=True')
        if dry.get('news') != 'ok':
            return _fail('dry_run news marker missing')

    scoped_calls: list[str] = []

    def _fake_scoped(scope: str, *, dry_run: bool = False):
        scoped_calls.append(scope)
        base = {'ok': True, 'scope': scope, 'warnings': []}
        base[scope if scope in ('news', 'runtime') else 'runtime'] = 'ok'
        if scope == 'news':
            base['news'] = 'ok'
        if scope == 'global':
            base['global'] = 'ok'
        if scope == 'govt':
            base['govt'] = 'ok'
        if scope == 'tv':
            base['tv'] = 'skipped'
        if scope == 'runtime':
            base['runtime'] = 'ok'
        return base

    with patch('scripts.refresh_closed_market_intelligence._router_mode', return_value=('RESEARCH_MODE', True)), \
         patch('scripts.refresh_local_intelligence.run_refresh_scoped', side_effect=_fake_scoped), \
         patch('scripts.refresh_closed_market_intelligence._run_script', return_value=(True, 'ok')):
        result = run_closed_market_refresh(dry_run=False, skip_reports=True)
        if result.get('ok') is not True:
            return _fail(f'live mock refresh failed: {result}')
        for scope in ('news', 'global', 'govt', 'runtime'):
            if scope not in scoped_calls:
                return _fail(f'expected run_refresh_scoped({scope!r})')
        if 'tv' in scoped_calls:
            return _fail('closed refresh must use refresh_tv_intelligence.py subprocess, not tv scope')
        if result.get('external_evidence') != 'ok':
            return _fail('external_evidence should be ok in mock run')

    from backend.analytics.source_freshness import get_source_freshness_report

    report = get_source_freshness_report()
    if report.get('ok') is not True:
        return _fail('source freshness report not ok')
    sources = report.get('sources') or {}
    for key in ('ai_package', 'external_evidence', 'prices', 'news'):
        if key not in sources:
            return _fail(f'source freshness missing sources.{key}')

    prices = sources.get('prices') or {}
    if report.get('market_closed') and prices.get('status') not in ('closed-market', 'fresh', 'stale', 'missing'):
        return _fail('prices status invalid for closed market')

    ai_pkg = sources.get('ai_package') or {}
    if ai_pkg.get('status') == 'fresh' and ai_pkg.get('age_hours') is not None and float(ai_pkg['age_hours']) > 2:
        return _fail('old AI package must not be labeled fresh')

    print('CLOSED_MARKET_REFRESH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
