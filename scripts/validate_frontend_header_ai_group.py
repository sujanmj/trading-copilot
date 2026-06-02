#!/usr/bin/env python3
"""
Validate Stage 44S header — AI: group with Router beside AI Hub.

Prints exactly FRONTEND_HEADER_AI_GROUP_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_HEADER_AI_GROUP_FAIL: {msg}', file=sys.stderr)
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

    if 'GUI_BUILD_STAGE_44U_LEFT_STATUS_ROW' not in src and 'GUI_BUILD_STAGE_44T_COMPACT_HEADER_FIXED' not in src and 'GUI_BUILD_STAGE_44S_AI_GROUP_ROUTER_FIXED' not in src:
        return _fail('GUI_BUILD_STAGE_44S/44T/44U marker missing')

    header_start = src.find('<header class="app-header"')
    header_end = src.find('</header>', header_start)
    if header_start < 0 or header_end < 0:
        return _fail('app-header block missing')
    header = src[header_start:header_end]

    main_row = _section(header, 'header-row-main', 'header-row-status')
    status_row = _section(header, 'header-row-status', 'header-body-boundary')
    if not main_row or not status_row:
        return _fail('header-row-main and header-row-status required')

    nav_group = _section(main_row, 'header-nav-group', '</div>')
    if 'AI:' not in nav_group and '>AI:</span>' not in nav_group and 'btn-group-label">AI:' not in main_row:
        return _fail('AI: label missing in header-row-main')

    mem = _button_classes(main_row, 'memoryNavBtn')
    brokers = _button_classes(main_row, 'brokersNavBtn')
    ai = _button_classes(main_row, 'aiHubNavBtn')
    router = _button_classes(main_row, 'routerNavBtn')
    if 'primary-nav-btn' not in mem or 'primary-nav-btn' not in router:
        return _fail('Memory and Router must use primary-nav-btn in line 1')

    mem_pos = main_row.find('memoryNavBtn')
    brokers_pos = main_row.find('brokersNavBtn')
    ai_pos = main_row.find('aiHubNavBtn')
    router_pos = main_row.find('routerNavBtn')
    if not (mem_pos < brokers_pos < ai_pos < router_pos):
        return _fail('line 1 order must be Memory, Brokers, AI Hub, Router')

    if 'routerNavBtn' in status_row:
        return _fail('Router must not appear in header-row-status')

    for token in ('reviewBtn', 'aiOpsBtn', 'apiStatus', 'guiModeBadge', '🔴 LIVE'):
        if token not in status_row:
            return _fail(f'status control missing from line 2: {token!r}')

    if 'id="brokerSourceRow"' not in main_row or 'id="newsSourceRow"' not in main_row:
        return _fail('broker/news source rows must remain in header-row-main')

    for fn in ('renderSourceFeed', '/api/debug/source-feed'):
        if fn not in src:
            return _fail(f'source feed wiring missing: {fn!r}')

    print('FRONTEND_HEADER_AI_GROUP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
