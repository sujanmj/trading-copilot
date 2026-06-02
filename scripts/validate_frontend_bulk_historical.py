#!/usr/bin/env python3
"""
Validate frontend bulk historical import markers in MarketMemoryPanel.js.

Prints FRONTEND_BULK_HISTORICAL_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'MarketMemoryPanel.js'

REQUIRED_MARKERS = (
    'Historical tickers',
    'Import report',
    'Replay report',
    'Quality anomalies',
    'low sample',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_BULK_HISTORICAL_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not PANEL.is_file():
        return _fail(f'missing {PANEL.relative_to(PROJECT_ROOT)}')

    panel_src = PANEL.read_text(encoding='utf-8')
    for token in REQUIRED_MARKERS:
        if token not in panel_src:
            return _fail(f'MarketMemoryPanel.js missing marker: {token!r}')

    print('FRONTEND_BULK_HISTORICAL_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
