#!/usr/bin/env python3
"""
Validate Stage 44T compact header — AI group stays on line 1.

Prints exactly FRONTEND_COMPACT_HEADER_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_COMPACT_HEADER_FAIL: {msg}', file=sys.stderr)
    return 1


def _section(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    end = src.find(end_marker, start)
    if start < 0 or end < 0:
        return ''
    return src[start:end]


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')

    if 'GUI_BUILD_STAGE_44U_LEFT_STATUS_ROW' not in src and 'GUI_BUILD_STAGE_44T_COMPACT_HEADER_FIXED' not in src:
        return _fail('GUI_BUILD_STAGE_44T/44U marker missing')

    header_start = src.find('<header class="app-header"')
    header_end = src.find('</header>', header_start)
    if header_start < 0 or header_end < 0:
        return _fail('app-header block missing')
    header = src[header_start:header_end]

    main_row = _section(header, 'header-row-main', 'header-row-status')
    status_row = _section(header, 'header-row-status', 'header-body-boundary')
    if not main_row or not status_row:
        return _fail('header-row-main and header-row-status required')

    if 'routerNavBtn' not in main_row:
        return _fail('Router must remain in header-row-main')
    if 'routerNavBtn' in status_row:
        return _fail('Router must not appear in header-row-status')

    ai_pos = main_row.find('aiHubNavBtn')
    router_pos = main_row.find('routerNavBtn')
    if ai_pos < 0 or router_pos < 0 or not (ai_pos < router_pos):
        return _fail('Router must follow AI Hub in header-row-main')

    for btn_id in ('memoryNavBtn', 'brokersNavBtn', 'aiHubNavBtn', 'routerNavBtn'):
        if btn_id not in main_row:
            return _fail(f'{btn_id} must appear in header-row-main')

    if 'id="brokerSourceRow"' not in main_row or 'id="newsSourceRow"' not in main_row:
        return _fail('broker/news source buttons must remain in header-row-main')

    if 'font-size: 11px' not in src or 'padding: 3px 7px' not in src:
        return _fail('compact primary-nav-btn sizing missing')
    if 'min-width: 1500px' not in src or 'flex-wrap: nowrap' not in src:
        return _fail('desktop nowrap media query missing')

    for token in ('reviewBtn', 'aiOpsBtn', 'apiStatus', 'guiModeBadge'):
        if token not in status_row:
            return _fail(f'status control missing from line 2: {token!r}')

    forbidden = (
        'sourcesToggleBtn', 'sourcesBar', 'Sources</button>',
        'brokers-menu', 'news-menu', '<details',
    )
    for token in forbidden:
        if token in header:
            return _fail(f'forbidden header artifact: {token!r}')

    for fn in ('renderSourceFeed', '/api/debug/source-feed'):
        if fn not in src:
            return _fail(f'source feed wiring missing: {fn!r}')

    print('FRONTEND_COMPACT_HEADER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
