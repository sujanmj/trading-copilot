#!/usr/bin/env python3
"""Unit tests for single-row header with AI + LIVE/API controls (Stage 48C)."""

from __future__ import annotations

import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'HEADER_CONTROL_ROW_LAYOUT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')
    src = INDEX.read_text(encoding='utf-8')
    header_start = src.find('<header class="app-header"')
    header_end = src.find('</header>', header_start)
    header = src[header_start:header_end]
    main_line = header[header.find('header-main-line'):header.find('header-body-boundary')]

    ai_pos = main_line.find('header-nav-group')
    live_pos = main_line.find('header-status-inline')
    brokers_pos = main_line.find('id="brokerSourceRow"')
    news_pos = main_line.find('id="newsSourceRow"')
    if min(ai_pos, live_pos, brokers_pos, news_pos) < 0:
        return _fail('AI, status-inline, brokers, or news group missing')
    if not (ai_pos < live_pos < brokers_pos < news_pos):
        return _fail('order must be AI, LIVE/API, BROKERS, NEWS on first row')

    for token in ('🧠 Memory', '🏛️ Budget', '🔴 LIVE', 'id="apiTargetBadge"', 'id="aiOpsBtn"', 'id="reviewBtn"'):
        if token not in main_line:
            return _fail(f'missing {token!r} on main row')

    if 'header-status-line' in main_line and 'display: none' not in src:
        pass
    if '<div class="header-status-line">' in header:
        return _fail('separate header-status-line row must be removed')

    print('HEADER_CONTROL_ROW_LAYOUT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
