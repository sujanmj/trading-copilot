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
        'data-tab="global"', 'data-tab="news"', 'data-tab="tv"',
        'data-tab="stats"', 'data-tab="history"',
    )
    for tab in required_tabs:
        if tab not in src:
            return _fail(f'missing tab {tab}')

    if 'myFeedMainContent' not in src or 'myFeedNavBtn' not in src:
        return _fail('My Feed workspace panel/nav missing')

    if re.search(r'data-tab=["\']memory["\']', src):
        return _fail('AI Hub must not include Mem tab (memory workspace only)')
    if 'id="tab-memory"' in src or '📚 Mem' in src:
        return _fail('AI Hub must not include Mem tab (memory workspace only)')
    if re.search(r'data-tab=["\']reddit["\']', src):
        return _fail('AI Hub must not include Reddit tab (replaced by My Feed)')

    if 'data-aihub-refresh-tab="${escapeHtml(tabId)}"' not in src and "data-aihub-refresh-tab=\"${escapeHtml(tabId)}\"" not in src:
        return _fail('missing dynamic per-tab refresh wiring')
    if 'refreshTabByPanel' not in src:
        return _fail('index.html must wire refreshTabByPanel')
    if 'tabTimestampHtml' not in src:
        return _fail('index.html must define tabTimestampHtml for per-tab freshness')

    if not re.search(r'font-size:\s*1[2-9]px', src):
        return _fail('expected +15% font scale (body/tabs >= 12px)')

    print('FRONTEND_AIHUB_TABS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
