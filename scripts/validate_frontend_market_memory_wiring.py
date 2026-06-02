#!/usr/bin/env python3
"""
Validate frontend Market Memory wiring (Stage 17B).

Scans frontend files for:
  - dashboard endpoint string
  - "Canonical Market Memory"
  - "Refresh Memory"
  - "Shadow Advisor only"
  - no runtime_snapshot fallback inside MarketMemoryPanel.js

Prints exactly FRONTEND_MARKET_MEMORY_WIRING_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = PROJECT_ROOT / 'frontend'
PANEL = FRONTEND / 'components' / 'MarketMemoryPanel.js'

REQUIRED_MARKERS = (
    '/api/debug/market-memory/dashboard',
    'Canonical Market Memory',
    'Refresh Memory',
    'Shadow Advisor only',
)

FORBIDDEN_IN_PANEL = (
    'runtime_snapshot',
    '/api/runtime_snapshot',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_MARKET_MEMORY_WIRING_FAIL: {msg}', file=sys.stderr)
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
            return _fail(f'MarketMemoryPanel.js missing marker: {token!r}')

    for token in FORBIDDEN_IN_PANEL:
        if token in panel_src:
            return _fail(f'MarketMemoryPanel.js must not reference {token!r}')

    index_html = FRONTEND / 'index.html'
    if not index_html.is_file():
        return _fail('missing frontend/index.html')

    index_src = _read(index_html)
    if 'memoryNavBtn' not in index_src or '🧠 Memory' not in index_src:
        return _fail('index.html missing top nav 🧠 Memory button (memoryNavBtn)')

    if 'MarketMemoryPanel.js' not in index_src:
        return _fail('index.html does not load MarketMemoryPanel.js')

    if 'memoryMainPanel' not in index_src:
        return _fail('index.html missing memoryMainPanel container')

    # Confirm dashboard endpoint appears somewhere in frontend (panel is canonical source)
    frontend_glob = list(FRONTEND.rglob('*'))
    text_files = [
        p for p in frontend_glob
        if p.is_file() and p.suffix.lower() in {'.js', '.html', '.tsx', '.ts', '.jsx'}
    ]
    if not any('/api/debug/market-memory/dashboard' in _read(p) for p in text_files if p.exists()):
        return _fail('dashboard endpoint string not found in frontend')

    # Guard against runtime_snapshot fallback wired into MarketMemory component
    fallback_pattern = re.compile(
        r'runtime_snapshot|getNormalizedSnapshot|RuntimeManager\.get',
        re.IGNORECASE,
    )
    if fallback_pattern.search(panel_src):
        return _fail('MarketMemoryPanel.js appears to use runtime snapshot fallback')

    print('FRONTEND_MARKET_MEMORY_WIRING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
