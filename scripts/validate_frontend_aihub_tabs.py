#!/usr/bin/env python3
"""
Validate Stage 20B AI Hub tabs: no Mem tab, per-tab refresh, tab-specific timestamps.

Prints exactly FRONTEND_AIHUB_TABS_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_AIHUB_TABS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not INDEX.is_file():
        return _fail(f'missing {INDEX.relative_to(PROJECT_ROOT)}')

    src = INDEX.read_text(encoding='utf-8')

    required_tabs = (
        'data-tab="brain"', 'data-tab="govt"', 'data-tab="scanner"', 'data-tab="markets"',
        'data-tab="global"', 'data-tab="news"', 'data-tab="tv"', 'data-tab="reddit"',
        'data-tab="stats"', 'data-tab="history"',
    )
    for tab in required_tabs:
        if tab not in src:
            return _fail(f'missing tab {tab}')

    if re.search(r'data-tab=["\']memory["\']', src):
        return _fail('AI Hub must not include Mem tab (memory workspace only)')
    if 'id="tab-memory"' in src or '📚 Mem' in src:
        return _fail('AI Hub must not include Mem tab (memory workspace only)')

    refresh_scopes = (
        'data-refresh-scope="runtime"', 'data-refresh-scope="govt"', 'data-refresh-scope="scanner"',
        'data-refresh-scope="prices"', 'data-refresh-scope="global"', 'data-refresh-scope="news"',
        'data-refresh-scope="tv"', 'data-refresh-scope="reddit"', 'data-refresh-scope="calibration"',
        'data-refresh-scope="journal"',
    )
    for scope in refresh_scopes:
        if scope not in src:
            return _fail(f'missing per-tab refresh {scope}')

    if 'dry_run: false' not in src.replace(' ', ''):
        if "dry_run: false" not in src and "'dry_run': false" not in src and '"dry_run": false' not in src:
            return _fail('tab refresh must POST dry_run: false')

    if 'tabTimestampHtml' not in src:
        return _fail('index.html must define tabTimestampHtml for per-tab freshness')

    if 'refreshTabByPanel' not in src:
        return _fail('index.html must wire refreshTabByPanel')

    if not re.search(r'font-size:\s*1[2-9]px', src):
        return _fail('expected +15% font scale (body/tabs >= 12px)')

    print('FRONTEND_AIHUB_TABS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
