#!/usr/bin/env python3
"""
Validate Stage 44U header — status row left-aligned under brand.

Prints exactly FRONTEND_HEADER_LEFT_STATUS_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_HEADER_LEFT_STATUS_FAIL: {msg}', file=sys.stderr)
    return 1


def _section(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    end = src.find(end_marker, start)
    if start < 0 or end < 0:
        return ''
    return src[start:end]


def _css_block(src: str, selector: str) -> str:
    pattern = re.compile(rf'{re.escape(selector)}\s*\{{([^}}]+)\}}', re.DOTALL)
    match = pattern.search(src)
    return match.group(1) if match else ''


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')

    if 'GUI_BUILD_STAGE_44U_LEFT_STATUS_ROW' not in src:
        return _fail('GUI_BUILD_STAGE_44U_LEFT_STATUS_ROW marker missing')

    if 'header-row-main' not in src or 'header-row-status' not in src:
        return _fail('header-row-main and header-row-status required')

    status_css = _css_block(src, '.header-row-status')
    if not status_css:
        return _fail('.header-row-status CSS missing')
    if 'justify-content:flex-start' not in status_css.replace(' ', '') and 'justify-content: flex-start' not in status_css:
        return _fail('header-row-status must use justify-content: flex-start')

    if re.search(r'\.header-row-status\s*\{[^}]*justify-content\s*:\s*flex-end', src):
        return _fail('header-row-status must not use justify-content: flex-end')

    if '.header-row-status .right-status' not in src:
        return _fail('header-row-status right-status override missing')

    header_start = src.find('<header class="app-header"')
    header_end = src.find('</header>', header_start)
    header = src[header_start:header_end] if header_start >= 0 and header_end >= 0 else ''

    main_row = _section(header, 'header-row-main', 'header-row-status')
    status_row = _section(header, 'header-row-status', 'header-body-boundary')
    if 'routerNavBtn' not in main_row:
        return _fail('Router must remain in header-row-main')

    for token in ('reviewBtn', 'aiOpsBtn', 'apiStatus', 'guiModeBadge', '🔴 LIVE'):
        if token not in status_row:
            return _fail(f'status control missing from line 2: {token!r}')

    for fn in ('renderSourceFeed', '/api/debug/source-feed'):
        if fn not in src:
            return _fail(f'source feed wiring missing: {fn!r}')

    print('FRONTEND_HEADER_LEFT_STATUS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
