#!/usr/bin/env python3
"""Validate frontend Daily Report Pack wiring."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'DailyReportPackPanel.js'
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
MEMORY = PROJECT_ROOT / 'frontend' / 'components' / 'MarketMemoryPanel.js'

REQUIRED = (
    '🗂 Daily Report Pack',
    'shadow analysis only',
    '/api/debug/daily-report-pack',
    'DailyReportPackPanel',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_DAILY_REPORT_PACK_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (PANEL, INDEX, MEMORY):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    combined = INDEX.read_text(encoding='utf-8') + PANEL.read_text(encoding='utf-8') + MEMORY.read_text(encoding='utf-8')
    for token in REQUIRED:
        if token not in combined:
            return _fail(f'missing marker: {token!r}')

    print('FRONTEND_DAILY_REPORT_PACK_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
