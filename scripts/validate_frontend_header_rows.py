#!/usr/bin/env python3
"""
Validate Stage 44O frontend header — 3 compact rows, flat nav, content below header.

Prints exactly FRONTEND_HEADER_ROWS_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_HEADER_ROWS_FAIL: {msg}', file=sys.stderr)
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
    forbidden = ('sourcesToggleBtn', 'sourcesBar', 'sources-bar', 'Sources</button>', 'Sources ▼')
    for token in forbidden:
        if token in src:
            return _fail(f'removed UI artifact still present: {token!r}')

    header_start_idx = src.find('<header class="app-header"')
    header_end_idx = src.find('</header>')
    if header_start_idx < 0 or header_end_idx < 0:
        return _fail('app-header block missing')
    header = src[header_start_idx:header_end_idx]

    if '⚡ AstraEdge AI' not in header:
        return _fail('AstraEdge AI branding missing')

    if 'header-row-main' not in header:
        return _fail('main nav row missing')

    if 'header-row-brokers' not in header or 'BROKERS:' not in header:
        return _fail('broker source row missing')

    if 'header-row-news' not in header or 'NEWS:' not in header:
        return _fail('news source row missing')

    dropdown_markers = (
        'brokers-menu', 'news-menu', 'astra-drop', 'BROKERS ▼', 'NEWS ▼',
        'activeDropdown', 'toggleAstraDropdown', '<details',
    )
    for marker in dropdown_markers:
        if marker in header:
            return _fail(f'dropdown artifact in header: {marker!r}')

    main_row = _section(header, 'header-row-main', 'header-row-brokers')
    mem = _button_classes(main_row, 'memoryNavBtn')
    brokers = _button_classes(main_row, 'brokersNavBtn')
    ai = _button_classes(main_row, 'aiHubNavBtn')
    if 'primary-nav-btn' not in mem or mem != brokers or mem != ai:
        return _fail('Memory, Brokers, AI Hub must share primary-nav-btn class')

    mem_pos = main_row.find('memoryNavBtn')
    brokers_pos = main_row.find('brokersNavBtn')
    ai_pos = main_row.find('aiHubNavBtn')
    router_pos = main_row.find('routerNavBtn')
    if not (mem_pos < brokers_pos < ai_pos < router_pos):
        return _fail('nav order must be Memory, Brokers, AI Hub, Router')

    if 'id="brokerSourceRow"' not in header or 'id="newsSourceRow"' not in header:
        return _fail('broker/news source row ids missing')

    main_pos = src.find('<div class="main"')
    header_end = src.find('</header>')
    if header_end < 0 or main_pos < header_end:
        return _fail('main content must start after header block')

    if '.app-header' not in src:
        return _fail('app-header styles missing')

    print('FRONTEND_HEADER_ROWS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
