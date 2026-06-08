#!/usr/bin/env python3
"""Unit tests for header AI nav first-row layout (Stage 48B/48C)."""

from __future__ import annotations

import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'HEADER_AI_NAV_LAYOUT_TEST_FAIL: {msg}', file=sys.stderr)
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
    if ai_pos < 0 or live_pos < 0 or brokers_pos < 0:
        return _fail('AI nav or inline status or brokers missing')
    if not (ai_pos < live_pos < brokers_pos):
        return _fail('AI nav must appear before LIVE/API before BROKERS')

    for label in ('🧠 Memory', '🏛️ Budget', '🏦 Brokers', '🤖 AI Hub', '🌍 Router'):
        if label not in main_line:
            return _fail(f'AI nav button missing: {label!r}')

    for token in ('🔴 LIVE', 'id="apiTargetBadge"', 'id="aiOpsBtn"', 'id="reviewBtn"'):
        if token not in main_line:
            return _fail(f'inline status missing {token!r}')

    print('HEADER_AI_NAV_LAYOUT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
