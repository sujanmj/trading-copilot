#!/usr/bin/env python3
"""
Validate FinalConfidencePanel includes historical simulation UI.

Usage:
  python scripts/validate_frontend_simulation_confidence.py

Prints exactly FRONTEND_SIMULATION_CONFIDENCE_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PANEL_PATH = PROJECT_ROOT / 'frontend' / 'components' / 'FinalConfidencePanel.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_SIMULATION_CONFIDENCE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not PANEL_PATH.is_file():
        return _fail(f'missing panel: {PANEL_PATH}')

    text = PANEL_PATH.read_text(encoding='utf-8')
    required = (
        'Historical Simulation',
        'strategy expectancy',
        'historical_simulation',
        'score_breakdown',
    )
    for token in required:
        if token not in text:
            return _fail(f'FinalConfidencePanel.js missing: {token}')

    print('FRONTEND_SIMULATION_CONFIDENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
