#!/usr/bin/env python3
"""
Validate frontend Confidence Calibration wiring (Stage 31).

Prints exactly FRONTEND_CONFIDENCE_CALIBRATION_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'FinalConfidencePanel.js'
MEMORY = PROJECT_ROOT / 'frontend' / 'components' / 'MarketMemoryPanel.js'

REQUIRED_PANEL = (
    'Calibration',
    'Calibration is analysis only',
    '/api/debug/confidence-calibration',
    'calibration_error',
    'overconfident',
    'underconfident',
)
REQUIRED_MEMORY = (
    'Calibration',
    '/api/debug/confidence-calibration',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_CONFIDENCE_CALIBRATION_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (PANEL, MEMORY):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    panel_src = PANEL.read_text(encoding='utf-8')
    memory_src = MEMORY.read_text(encoding='utf-8')

    for token in REQUIRED_PANEL:
        if token not in panel_src:
            return _fail(f'FinalConfidencePanel.js missing marker: {token!r}')

    for token in REQUIRED_MEMORY:
        if token not in memory_src:
            return _fail(f'MarketMemoryPanel.js missing marker: {token!r}')

    print('FRONTEND_CONFIDENCE_CALIBRATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
