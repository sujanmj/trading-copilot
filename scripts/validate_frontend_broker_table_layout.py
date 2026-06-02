#!/usr/bin/env python3
"""
Validate Stage 43 broker evidence table layout in frontend.

Checks:
  - shared bi-evidence-table styling with fixed ticker/direction/class columns
  - title column truncate + title attribute for hover
  - BrokerIntelligencePanel uses renderEvidenceTable for evidence sections

Prints exactly FRONTEND_BROKER_TABLE_LAYOUT_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'BrokerIntelligencePanel.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_BROKER_TABLE_LAYOUT_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def main() -> int:
    for path in (INDEX, PANEL):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = _read(INDEX)
    panel_src = _read(PANEL)

    for token in (
        'bi-evidence-table',
        'bi-col-ticker',
        'bi-col-direction',
        'bi-col-class',
        'bi-col-title',
    ):
        if token not in index_src:
            return _fail(f'index.html missing CSS marker: {token!r}')

    ticker_block = re.search(r'\.bi-evidence-table \.bi-col-ticker\s*\{([^}]*)\}', index_src)
    direction_block = re.search(r'\.bi-evidence-table \.bi-col-direction\s*\{([^}]*)\}', index_src)
    title_block = re.search(r'\.bi-evidence-table \.bi-col-title\s*\{([^}]*)\}', index_src)

    if not ticker_block or 'width' not in ticker_block.group(1):
        return _fail('.bi-col-ticker must define fixed width')
    if not direction_block or 'text-align' not in direction_block.group(1):
        return _fail('.bi-col-direction must be centered')
    if not title_block or 'text-overflow' not in title_block.group(1):
        return _fail('.bi-col-title must truncate long titles')

    for token in ('renderEvidenceTable', 'bi-evidence-table', 'bi-col-ticker', 'bi-col-title'):
        if token not in panel_src:
            return _fail(f'BrokerIntelligencePanel.js missing marker: {token!r}')

    if 'title="${titleEsc}"' not in panel_src and "title=\"${titleEsc}\"" not in panel_src:
        return _fail('BrokerIntelligencePanel.js must set title attribute on evidence rows')

    for section in (
        'Broker candidates',
        'Stock news evidence',
        'Market context',
        'Macro context',
        'Latest collected external ideas',
    ):
        if section not in panel_src:
            return _fail(f'BrokerIntelligencePanel.js missing section label: {section!r}')

    if panel_src.count('renderEvidenceTable') < 2:
        return _fail('renderEvidenceTable must be used for external evidence and collector tables')

    print('FRONTEND_BROKER_TABLE_LAYOUT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
