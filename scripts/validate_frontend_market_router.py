#!/usr/bin/env python3
"""
Validate frontend Market Router card wiring (Stage 24).

Scans frontend files for:
  - /api/debug/market-router endpoint
  - MarketRouterCard.js component
  - required UI labels (Active Mode, India session, USA session, etc.)

Prints exactly FRONTEND_MARKET_ROUTER_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = PROJECT_ROOT / 'frontend'
PANEL = FRONTEND / 'components' / 'MarketRouterCard.js'
INDEX = FRONTEND / 'index.html'

REQUIRED_MARKERS = (
    '/api/debug/market-router',
    'Active Mode',
    'India session',
    'USA session',
    'Recommended focus',
    'Next India open',
    'Next USA open',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_MARKET_ROUTER_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def main() -> int:
    if not PANEL.is_file():
        return _fail(f'missing {PANEL.relative_to(PROJECT_ROOT)}')

    panel_src = _read(PANEL)
    for token in REQUIRED_MARKERS:
        if token not in panel_src:
            return _fail(f'MarketRouterCard.js missing marker: {token!r}')

    if not INDEX.is_file():
        return _fail('missing frontend/index.html')

    index_src = _read(INDEX)
    if 'MarketRouterCard.js' not in index_src:
        return _fail('index.html does not load MarketRouterCard.js')
    if 'marketRouterCardHost' not in index_src:
        return _fail('index.html missing marketRouterCardHost container')
    if 'MarketRouterCard.init' not in index_src:
        return _fail('index.html missing MarketRouterCard.init wiring')

    print('FRONTEND_MARKET_ROUTER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
