#!/usr/bin/env python3
"""
Validate Stage 44AB wide AstraEdge logo in header grid.

Prints exactly FRONTEND_WIDE_LOGO_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
WIDE_LOGO = PROJECT_ROOT / 'frontend' / 'assets' / 'astraedge-logo-wide.png'


def _fail(msg: str) -> int:
    print(f'FRONTEND_WIDE_LOGO_FAIL: {msg}', file=sys.stderr)
    return 1


def _section(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    end = src.find(end_marker, start)
    if start < 0 or end < 0:
        return ''
    return src[start:end]


def _parse_px(value: str) -> float | None:
    match = re.search(r'([\d.]+)\s*px', value)
    return float(match.group(1)) if match else None


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    if not WIDE_LOGO.is_file():
        return _fail('frontend/assets/astraedge-logo-wide.png missing')

    src = INDEX.read_text(encoding='utf-8')

    if (
        'GUI_BUILD_STAGE_44AC_BLACK_HEADER_SOURCE_APPS' not in src
        and 'GUI_BUILD_STAGE_44AB_WIDE_LOGO_FIXED' not in src
        and 'GUI_BUILD_STAGE_44AD_ELECTRON_EMBEDDED_SOURCE_BROWSER' not in src
        and 'GUI_BUILD_STAGE_44AE_WEB_EXTERNAL_SOURCES' not in src
        and 'GUI_BUILD_STAGE_44AF_TEXT_DATA_CLEANUP' not in src
    ):
        return _fail('GUI_BUILD_STAGE_44AB/44AC/44AD/44AE/44AF marker missing')

    if 'astraedge-logo-wide.png' not in src:
        return _fail('astraedge-logo-wide.png not referenced')

    if 'astraedge-logo-img' not in src:
        return _fail('astraedge-logo-img class missing')

    brand_css = _section(src, '.brand-block {', '}')
    if not brand_css:
        return _fail('.brand-block CSS missing')

    row_norm = re.sub(r'\s+', ' ', brand_css)
    spans_two = (
        'grid-row: 1 / span 2' in row_norm
        or 'grid-row:1 / span 2' in row_norm.replace(' ', '')
        or 'grid-row: 1/span 2' in row_norm.replace(' ', '')
    )
    if not spans_two:
        return _fail('brand-block must span two rows (grid-row: 1 / span 2)')

    grid_css = _section(src, '.header-grid {', '}')
    if not grid_css:
        return _fail('.header-grid CSS missing')

    cols_match = re.search(r'grid-template-columns:\s*([^;]+)', grid_css)
    if not cols_match:
        return _fail('header-grid grid-template-columns missing')

    left_col = _parse_px(cols_match.group(1).split()[0])
    if left_col is None or left_col < 240:
        return _fail(f'header-grid left column must be at least 240px (found {left_col})')

    main_css = _section(src, '.header-main-line {', '}')
    status_css = _section(src, '.header-status-line {', '}')
    for name, block in (('header-main-line', main_css), ('header-status-line', status_css)):
        if not block:
            return _fail(f'{name} CSS missing')
        norm = block.replace(' ', '')
        if 'grid-column:2' not in norm and 'grid-column: 2' not in block:
            return _fail(f'{name} must use grid-column: 2')

    for fn in ('renderSourceFeed', '/api/debug/source-feed'):
        if fn not in src:
            return _fail(f'source feed wiring missing: {fn!r}')

    print('FRONTEND_WIDE_LOGO_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
