#!/usr/bin/env python3
"""
Validate Stage 44AA large AstraEdge logo spanning both header rows.

Prints exactly FRONTEND_LARGE_LOGO_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_LARGE_LOGO_FAIL: {msg}', file=sys.stderr)
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

    src = INDEX.read_text(encoding='utf-8')

    if 'GUI_BUILD_STAGE_44AA_LARGE_LOGO_FIXED' not in src:
        return _fail('GUI_BUILD_STAGE_44AA_LARGE_LOGO_FIXED marker missing')

    if 'astraedge-logo-img' not in src:
        return _fail('astraedge-logo-img class missing')

    logo_css = _section(src, '.astraedge-logo-img {', '}')
    if not logo_css:
        return _fail('.astraedge-logo-img CSS missing')

    logo_height = _parse_px(logo_css)
    if logo_height is None or logo_height < 56:
        return _fail(f'logo height must be at least 56px (found {logo_height})')

    grid_css = _section(src, '.header-grid {', '}')
    if not grid_css:
        return _fail('.header-grid CSS missing')

    cols_match = re.search(r'grid-template-columns:\s*([^;]+)', grid_css)
    if not cols_match:
        return _fail('header-grid grid-template-columns missing')

    left_col = _parse_px(cols_match.group(1).split()[0])
    if left_col is None or left_col < 190:
        return _fail(f'header-grid left column must be at least 190px (found {left_col})')

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

    main_css = _section(src, '.header-main-line {', '}')
    status_css = _section(src, '.header-status-line {', '}')
    for name, block in (('header-main-line', main_css), ('header-status-line', status_css)):
        norm = block.replace(' ', '')
        if 'grid-column:2' not in norm and 'grid-column: 2' not in block:
            return _fail(f'{name} must use grid-column: 2')

    header_start = src.find('<header class="app-header"')
    header_end = src.find('</header>', header_start)
    if header_start < 0 or header_end < 0:
        return _fail('app-header block missing')
    header = src[header_start:header_end]

    main_line = _section(header, 'class="header-main-line"', 'class="header-status-line"')
    status_line = _section(header, 'class="header-status-line"', '</div>')
    if not main_line or not status_line:
        return _fail('header-main-line and header-status-line required')

    mem_pos = main_line.find('memoryNavBtn')
    brokers_pos = main_line.find('brokersNavBtn')
    ai_pos = main_line.find('aiHubNavBtn')
    router_pos = main_line.find('routerNavBtn')
    if not (mem_pos < brokers_pos < ai_pos < router_pos):
        return _fail('Memory, Brokers, AI Hub, Router order required')

    if 'routerNavBtn' in status_line:
        return _fail('Router must follow AI Hub in header-main-line only')

    for fn in ('renderSourceFeed', '/api/debug/source-feed'):
        if fn not in src:
            return _fail(f'source feed wiring missing: {fn!r}')

    print('FRONTEND_LARGE_LOGO_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
