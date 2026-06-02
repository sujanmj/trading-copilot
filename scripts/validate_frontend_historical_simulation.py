#!/usr/bin/env python3
"""
Validate frontend Historical Simulation wiring (Stage 34).

Scans MarketMemoryPanel.js for:
  - Historical Simulation section title
  - disclaimer text
  - simulation stats wiring

Prints exactly FRONTEND_HISTORICAL_SIMULATION_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'MarketMemoryPanel.js'

REQUIRED_MARKERS = (
    'Historical Simulation',
    'Simulated predictions are backtest samples, not live predictions.',
    'simulation',
    'simulated_predictions',
    'strategy_performance',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_HISTORICAL_SIMULATION_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not PANEL.is_file():
        return _fail(f'missing {PANEL.relative_to(PROJECT_ROOT)}')

    panel_src = PANEL.read_text(encoding='utf-8')
    for token in REQUIRED_MARKERS:
        if token not in panel_src:
            return _fail(f'MarketMemoryPanel.js missing marker: {token!r}')

    print('FRONTEND_HISTORICAL_SIMULATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
