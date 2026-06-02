#!/usr/bin/env python3
"""
Validate Stage 23 Brokers workspace wiring in frontend.

Prints exactly FRONTEND_BROKER_WORKSPACE_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'BrokerIntelligencePanel.js'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'

REQUIRED_INDEX = (
    'brokersNavBtn',
    '🏦 Brokers',
    'workspace-brokers',
    'brokersMainPanel',
    'BrokerIntelligencePanel.js',
    'External broker/app evidence',
)
REQUIRED_PANEL = (
    '/api/debug/broker-intelligence',
    '/api/debug/our-vs-broker',
    'collect_broker_app_predictions.py',
    'import_broker_predictions.py',
    'broker_prediction_inbox',
)
REQUIRED_WORKSPACE = (
    "'brokers'",
    'brokersMainPanel',
    'BrokerIntelligencePanel',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_BROKER_WORKSPACE_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def main() -> int:
    for path in (INDEX, PANEL, WORKSPACE):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = _read(INDEX)
    panel_src = _read(PANEL)
    workspace_src = _read(WORKSPACE)

    for token in REQUIRED_INDEX:
        if token not in index_src:
            return _fail(f'index.html missing marker: {token!r}')

    for token in REQUIRED_PANEL:
        if token not in panel_src:
            return _fail(f'BrokerIntelligencePanel.js missing marker: {token!r}')

    for token in REQUIRED_WORKSPACE:
        if token not in workspace_src:
            return _fail(f'WorkspaceManager.js missing marker: {token!r}')

    if "data-workspace=\"brokers\"" not in index_src and "data-workspace='brokers'" not in index_src:
        if '.main[data-workspace="brokers"]' not in index_src:
            return _fail('index.html missing brokers workspace CSS selector')

    print('FRONTEND_BROKER_WORKSPACE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
