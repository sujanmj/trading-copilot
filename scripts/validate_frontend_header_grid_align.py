#!/usr/bin/env python3
"""
Validate Stage 44X header grid — brand left, controls right column.

Prints exactly FRONTEND_HEADER_GRID_ALIGN_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_HEADER_GRID_ALIGN_FAIL: {msg}', file=sys.stderr)
    return 1


def _section(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    end = src.find(end_marker, start)
    if start < 0 or end < 0:
        return ''
    return src[start:end]


def _button_classes(block: str, btn_id: str) -> str:
    pattern = re.compile(
        rf'<button[^>]*id="{re.escape(btn_id)}"[^>]*class="([^"]+)"',
        re.IGNORECASE,
    )
    match = pattern.search(block)
    if match:
        return match.group(1)
    pattern2 = re.compile(
        rf'<button[^>]*class="([^"]+)"[^>]*id="{re.escape(btn_id)}"',
        re.IGNORECASE,
    )
    match2 = pattern2.search(block)
    return match2.group(1) if match2 else ''


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')

    if (
        'GUI_BUILD_STAGE_44AC_BLACK_HEADER_SOURCE_APPS' not in src
        and 'GUI_BUILD_STAGE_44AB_WIDE_LOGO_FIXED' not in src
        and 'GUI_BUILD_STAGE_44AA_LARGE_LOGO_FIXED' not in src
        and 'GUI_BUILD_STAGE_44Z_IMAGE_LOGO_FIXED' not in src
        and 'GUI_BUILD_STAGE_44Y_CUSTOM_LOGO_MARK' not in src
        and 'GUI_BUILD_STAGE_44X_HEADER_GRID_ALIGN_FIXED' not in src
    ):
        return _fail('GUI_BUILD_STAGE_44X/44Y/44Z/44AA/44AB/44AC marker missing')

    grid_css = _section(src, '.header-grid {', '}')
    if grid_css:
        cols_match = re.search(r'grid-template-columns:\s*([^;]+)', grid_css)
        if cols_match:
            left_match = re.search(r'([\d.]+)\s*px', cols_match.group(1))
            if left_match:
                left_col = float(left_match.group(1))
                if left_col < 240:
                    return _fail(f'header-grid left column must be at least 240px (found {left_col})')

    for token in ('header-grid', 'brand-block', 'header-main-line', 'header-status-line'):
        if token not in src:
            return _fail(f'missing layout token: {token!r}')

    if '.header-grid' not in src or 'grid-template-columns' not in src:
        return _fail('header-grid CSS missing')

    status_css = _section(src, '.header-status-line {', '}')
    if 'grid-column: 2' not in status_css.replace(' ', '') and 'grid-column:2' not in status_css.replace(' ', ''):
        if 'grid-column: 2' not in src and 'grid-column:2' not in src.replace(' ', ''):
            return _fail('header-status-line must use grid-column: 2')

    header_start = src.find('<header class="app-header"')
    header_end = src.find('</header>', header_start)
    if header_start < 0 or header_end < 0:
        return _fail('app-header block missing')
    header = src[header_start:header_end]

    main_line = _section(header, 'class="header-main-line"', 'class="header-status-line"')
    status_line = _section(header, 'class="header-status-line"', '</div>')
    if not main_line or not status_line:
        return _fail('header-main-line and header-status-line required')

    for label in ('BROKERS:', 'NEWS:', 'AI:'):
        if label not in main_line:
            return _fail(f'{label} must appear in header-main-line')

    mem_pos = main_line.find('memoryNavBtn')
    brokers_pos = main_line.find('brokersNavBtn')
    ai_pos = main_line.find('aiHubNavBtn')
    router_pos = main_line.find('routerNavBtn')
    if not (mem_pos < brokers_pos < ai_pos < router_pos):
        return _fail('Memory, Brokers, AI Hub, Router order required in header-main-line')

    if 'routerNavBtn' in status_line:
        return _fail('Router must not appear in header-status-line')

    for token in ('reviewBtn', 'aiOpsBtn', 'apiStatus', 'guiModeBadge', 'live-badge'):
        if token not in status_line:
            return _fail(f'status control missing from header-status-line: {token!r}')

    if 'id="brokerSourceRow"' not in main_line or 'id="newsSourceRow"' not in main_line:
        return _fail('broker/news source rows must remain in header-main-line')

    forbidden = (
        'sourcesToggleBtn', 'Sources</button>', 'brokers-menu', 'news-menu', '<details',
    )
    for token in forbidden:
        if token in header:
            return _fail(f'forbidden header artifact: {token!r}')

    for fn in ('renderSourceFeed', '/api/debug/source-feed'):
        if fn not in src:
            return _fail(f'source feed wiring missing: {fn!r}')

    if 'AstraEdge AI' not in header:
        return _fail('AstraEdge AI branding missing')

    print('FRONTEND_HEADER_GRID_ALIGN_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
