#!/usr/bin/env python3
"""
Validate frontend Historical Learning wiring (Stage 25).

Scans MarketMemoryPanel.js for:
  - Historical Learning section title
  - /api/debug/historical-learning endpoint
  - ambiguous candle warning marker

Prints exactly FRONTEND_HISTORICAL_LEARNING_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = PROJECT_ROOT / 'frontend'
PANEL = FRONTEND / 'components' / 'MarketMemoryPanel.js'

REQUIRED_MARKERS = (
    'Historical Learning',
    '/api/debug/historical-learning',
    'ambiguous_daily_candle',
    'price_row_count',
    'top_tickers',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_HISTORICAL_LEARNING_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not PANEL.is_file():
        return _fail(f'missing {PANEL.relative_to(PROJECT_ROOT)}')

    panel_src = PANEL.read_text(encoding='utf-8')
    for token in REQUIRED_MARKERS:
        if token not in panel_src:
            return _fail(f'MarketMemoryPanel.js missing marker: {token!r}')

    print('FRONTEND_HISTORICAL_LEARNING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
