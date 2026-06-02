#!/usr/bin/env python3
"""
Validate frontend Market Router holiday calendar UI (Stage 29).

Scans frontend/components/MarketRouterCard.js for required holiday labels.

Prints exactly FRONTEND_MARKET_HOLIDAYS_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'MarketRouterCard.js'

REQUIRED_MARKERS = (
    'Holiday calendar',
    'Next India holiday',
    'Next USA holiday',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_MARKET_HOLIDAYS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not PANEL.is_file():
        return _fail(f'missing {PANEL.relative_to(PROJECT_ROOT)}')

    src = PANEL.read_text(encoding='utf-8')
    for token in REQUIRED_MARKERS:
        if token not in src:
            return _fail(f'MarketRouterCard.js missing marker: {token!r}')

    print('FRONTEND_MARKET_HOLIDAYS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
