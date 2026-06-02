#!/usr/bin/env python3
"""
Validate Stage 43B broker workspace font and table readability.

Checks:
  - Broker workspace base font matches AI Hub readability (~14px)
  - Evidence table headers/rows have readable padding
  - Title column wraps with ellipsis clamp; direction uses badge styling

Prints exactly FRONTEND_BROKER_FONT_LAYOUT_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'BrokerIntelligencePanel.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_BROKER_FONT_LAYOUT_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def _block(css: str, selector: str) -> str | None:
    pattern = re.escape(selector) + r'\s*\{([^}]*)\}'
    match = re.search(pattern, css, re.DOTALL)
    return match.group(1) if match else None


def main() -> int:
    for path in (INDEX, PANEL):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = _read(INDEX)
    panel_src = _read(PANEL)

    brokers_panel = _block(index_src, '.brokers-main-panel')
    if not brokers_panel or 'font-size' not in brokers_panel:
        return _fail('.brokers-main-panel must set a larger base font-size')

    if not re.search(r'font-size\s*:\s*1[34]px', brokers_panel):
        return _fail('.brokers-main-panel base font should be 13px or 14px')

    table_block = _block(index_src, '.brokers-main-panel .bi-table')
    if not table_block or 'font-size' not in table_block:
        return _fail('.brokers-main-panel .bi-table must increase table font-size')

    th_block = _block(index_src, '.brokers-main-panel .bi-table th')
    td_block = _block(index_src, '.bi-evidence-table td')
    if not th_block or 'padding' not in th_block:
        return _fail('broker table headers need readable padding')
    if not td_block or 'padding' not in td_block:
        return _fail('evidence table rows need readable padding')

    title_block = _block(index_src, '.bi-evidence-table .bi-col-title')
    if not title_block:
        return _fail('.bi-col-title CSS block missing')
    if 'word-break' not in title_block and 'white-space' not in title_block:
        return _fail('.bi-col-title must wrap or clamp long titles')
    if 'text-overflow' not in title_block:
        return _fail('.bi-col-title must include text-overflow for long titles')

    direction_block = _block(index_src, '.bi-evidence-table .bi-col-direction')
    if not direction_block or 'text-align' not in direction_block:
        return _fail('.bi-col-direction must be centered')

    if 'bi-direction-badge' not in index_src:
        return _fail('missing bi-direction-badge styling for direction column')

    for token in ('renderDirectionBadge', 'bi-direction-badge'):
        if token not in panel_src:
            return _fail(f'BrokerIntelligencePanel.js missing marker: {token!r}')

    print('FRONTEND_BROKER_FONT_LAYOUT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
