#!/usr/bin/env python3
"""
Validate frontend Tomorrow Watchlist wiring.

Prints exactly FRONTEND_TOMORROW_WATCHLIST_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'FinalConfidencePanel.js'

REQUIRED_MARKERS = (
    '📋 Tomorrow Watchlist',
    'Shadow watchlist only',
    '/api/debug/tomorrow-watchlist',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_TOMORROW_WATCHLIST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not PANEL.is_file():
        return _fail(f'missing {PANEL.relative_to(PROJECT_ROOT)}')

    src = PANEL.read_text(encoding='utf-8')
    for token in REQUIRED_MARKERS:
        if token not in src:
            return _fail(f'FinalConfidencePanel.js missing marker: {token!r}')

    print('FRONTEND_TOMORROW_WATCHLIST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
