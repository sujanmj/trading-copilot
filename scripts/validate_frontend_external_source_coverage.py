#!/usr/bin/env python3
"""
Validate frontend external source coverage wiring.

Prints FRONTEND_EXTERNAL_SOURCE_COVERAGE_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BROKER_PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'BrokerIntelligencePanel.js'
DRP_PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'DailyReportPackPanel.js'
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'

REQUIRED = (
    'External Source Coverage',
    'External evidence only',
    '/api/debug/external-source-coverage',
    'collected_items',
    'source_count',
    'unique_tickers',
    'latest_sources',
    'warnings',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_EXTERNAL_SOURCE_COVERAGE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (BROKER_PANEL, DRP_PANEL, INDEX):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    combined = (
        BROKER_PANEL.read_text(encoding='utf-8')
        + DRP_PANEL.read_text(encoding='utf-8')
        + INDEX.read_text(encoding='utf-8')
    )
    for token in REQUIRED:
        if token not in combined:
            return _fail(f'missing marker: {token!r}')

    print('FRONTEND_EXTERNAL_SOURCE_COVERAGE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
