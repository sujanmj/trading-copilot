#!/usr/bin/env python3
"""
Validate frontend Final Confidence wiring (Stage 26).

Prints exactly FRONTEND_FINAL_CONFIDENCE_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'FinalConfidencePanel.js'
MEMORY = PROJECT_ROOT / 'frontend' / 'components' / 'MarketMemoryPanel.js'

REQUIRED_INDEX = (
    'FinalConfidencePanel.js',
)
REQUIRED_PANEL = (
    '/api/debug/final-confidence',
    'Shadow confidence only',
    'buy_candidate',
    'no_decision',
    'score breakdown',
)
REQUIRED_MEMORY = (
    'Final Confidence',
    '/api/debug/final-confidence/report',
    'FinalConfidencePanel',
    'Shadow confidence only',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_FINAL_CONFIDENCE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (INDEX, PANEL, MEMORY):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    panel_src = PANEL.read_text(encoding='utf-8')
    memory_src = MEMORY.read_text(encoding='utf-8')

    for token in REQUIRED_INDEX:
        if token not in index_src:
            return _fail(f'index.html missing marker: {token!r}')

    for token in REQUIRED_PANEL:
        if token not in panel_src:
            return _fail(f'FinalConfidencePanel.js missing marker: {token!r}')

    for token in REQUIRED_MEMORY:
        if token not in memory_src:
            return _fail(f'MarketMemoryPanel.js missing marker: {token!r}')

    print('FRONTEND_FINAL_CONFIDENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
