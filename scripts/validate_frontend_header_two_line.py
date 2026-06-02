#!/usr/bin/env python3
"""
Validate Stage 44R two-line header layout in frontend/index.html.

Prints exactly FRONTEND_HEADER_TWO_LINE_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_HEADER_TWO_LINE_FAIL: {msg}', file=sys.stderr)
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

    if 'GUI_BUILD_STAGE_44S_AI_GROUP_ROUTER_FIXED' not in src and 'GUI_BUILD_STAGE_44R_TWO_LINE_HEADER' not in src:
        return _fail('header build marker missing (44S or 44R)')

    if '⚡ AstraEdge AI' not in src:
        return _fail('AstraEdge AI branding missing')

    if 'header-row-brokers' in src or 'header-row-news' in src:
        return _fail('legacy three-row header classes must be removed')

    header_start = src.find('<header class="app-header"')
    header_end = src.find('</header>', header_start)
    if header_start < 0 or header_end < 0:
        return _fail('app-header block missing')
    header = src[header_start:header_end]

    main_row = _section(header, 'header-row-main', 'header-row-status')
    status_row = _section(header, 'header-row-status', 'header-body-boundary')
    if not main_row or not status_row:
        return _fail('header-row-main and header-row-status required')

    if 'id="brokerSourceRow"' not in main_row:
        return _fail('brokerSourceRow must appear in header-row-main')
    if 'id="newsSourceRow"' not in main_row:
        return _fail('newsSourceRow must appear in header-row-main')

    for label in ('Angel', 'Zerodha', 'Groww', 'Upstox', 'IndMoney', '💼 Portfolio'):
        if label not in main_row:
            return _fail(f'broker button missing from line 1: {label!r}')

    for label in ('MC', 'ET', 'Mint', 'NDTV', '📱 Inshorts', '🤖 Reddit', 'ET Now', 'CNBC', 'NSE'):
        if label not in main_row:
            return _fail(f'news button missing from line 1: {label!r}')

    mem = _button_classes(main_row, 'memoryNavBtn')
    brokers = _button_classes(main_row, 'brokersNavBtn')
    ai = _button_classes(main_row, 'aiHubNavBtn')
    router = _button_classes(main_row, 'routerNavBtn')
    if 'primary-nav-btn' not in mem or mem != brokers or mem != ai:
        return _fail('Memory, Brokers, AI Hub must share primary-nav-btn class in line 1')

    mem_pos = main_row.find('memoryNavBtn')
    brokers_pos = main_row.find('brokersNavBtn')
    ai_pos = main_row.find('aiHubNavBtn')
    router_pos = main_row.find('routerNavBtn')
    if router_pos > 0:
        if not (mem_pos < brokers_pos < ai_pos < router_pos):
            return _fail('line 1 nav order must be Memory, Brokers, AI Hub, Router')
        if 'routerNavBtn' in status_row:
            return _fail('Router must not appear in header-row-status when in line 1')
    else:
        if not (mem_pos < brokers_pos < ai_pos):
            return _fail('line 1 nav order must be Memory, Brokers, AI Hub')
        if 'routerNavBtn' not in status_row:
            return _fail('Router must appear in header-row-status')

    for token in ('reviewBtn', 'aiOpsBtn', 'apiStatus', 'guiModeBadge', '🔴 LIVE'):
        if token not in status_row:
            return _fail(f'status control missing from line 2: {token!r}')

    forbidden = (
        'sourcesToggleBtn', 'sourcesBar', 'sources-bar', 'Sources</button>',
        'brokers-menu', 'news-menu', 'astra-drop', 'BROKERS ▼', 'NEWS ▼', '<details',
    )
    for token in forbidden:
        if token in header:
            return _fail(f'forbidden header artifact: {token!r}')

    for fn in ('renderSourceFeed', '/api/debug/source-feed', 'Open External', 'Back to Dashboard'):
        if fn not in src:
            return _fail(f'source feed wiring missing: {fn!r}')

    print('FRONTEND_HEADER_TWO_LINE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
