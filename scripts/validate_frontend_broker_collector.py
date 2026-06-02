#!/usr/bin/env python3
"""
Validate frontend broker/app collector wiring.

Prints exactly FRONTEND_BROKER_COLLECTOR_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'BrokerIntelligencePanel.js'
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'

REQUIRED_PANEL = (
    'Latest collected external ideas',
    'Collected external evidence',
    'broker-app-collector',
    '/api/debug/broker-app-collector',
    'collect_broker_app_predictions.py',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_BROKER_COLLECTOR_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not PANEL.is_file():
        return _fail(f'missing {PANEL.relative_to(PROJECT_ROOT)}')

    panel_src = PANEL.read_text(encoding='utf-8')
    for token in REQUIRED_PANEL:
        if token not in panel_src:
            return _fail(f'BrokerIntelligencePanel.js missing marker: {token!r}')

    if INDEX.is_file():
        index_src = INDEX.read_text(encoding='utf-8')
        if 'BrokerIntelligencePanel.js' not in index_src:
            return _fail('index.html missing BrokerIntelligencePanel.js include')

    print('FRONTEND_BROKER_COLLECTOR_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
