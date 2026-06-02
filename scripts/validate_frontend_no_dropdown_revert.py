#!/usr/bin/env python3
"""
Validate Stage 44L emergency revert — full flat nav, no dropdowns.

Prints exactly FRONTEND_NO_DROPDOWN_REVERT_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_NO_DROPDOWN_REVERT_FAIL: {msg}', file=sys.stderr)
    return 1


def _topbar_block(src: str) -> str:
    start = src.find('<div class="topbar">')
    end = src.find('<div class="main"', start)
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
    topbar = _topbar_block(src)
    if not topbar:
        return _fail('topbar block missing')

    if 'GUI_BUILD_STAGE_44O_HEADER_FEED_FRESHNESS' not in src:
        return _fail('GUI_BUILD_STAGE_44O_HEADER_FEED_FRESHNESS marker missing')

    if '⚡ AstraEdge AI' not in src:
        return _fail('AstraEdge AI branding missing')

    if 'BROKERS:' not in topbar:
        return _fail('BROKERS: label missing')

    if 'NEWS:' not in topbar:
        return _fail('NEWS: label missing')

    dropdown_markers = (
        'brokers-menu',
        'news-menu',
        'astra-drop',
        'brokersMenuBtn',
        'newsMenuBtn',
        'BROKERS ▼',
        'NEWS ▼',
        'BROKERS ▾',
        'activeDropdown',
        'toggleAstraDropdown',
        'closeNavDropdowns',
        'data-astra-drop',
    )
    for marker in dropdown_markers:
        if marker in src:
            return _fail(f'dropdown artifact must be removed: {marker!r}')

    if '<details' in topbar:
        return _fail('details dropdown must not appear in topbar')

    required_flat = (
        'Angel', 'Zerodha', 'Groww', 'Upstox', 'IndMoney', '💼 Portfolio',
        'MC', 'ET', 'Mint', 'NDTV', '📱 Inshorts', '🤖 Reddit', 'ET Now', 'CNBC', 'NSE',
    )
    for label in required_flat:
        if label not in topbar:
            return _fail(f'flat nav button missing: {label!r}')

    mem = _button_classes(topbar, 'memoryNavBtn')
    brokers = _button_classes(topbar, 'brokersNavBtn')
    ai = _button_classes(topbar, 'aiHubNavBtn')
    if 'primary-nav-btn' not in mem or mem != brokers or mem != ai:
        return _fail('Memory, Brokers, AI Hub must share primary-nav-btn class')

    mem_pos = topbar.find('memoryNavBtn')
    brokers_pos = topbar.find('brokersNavBtn')
    ai_pos = topbar.find('aiHubNavBtn')
    router_pos = topbar.find('routerNavBtn')
    if not (mem_pos < brokers_pos < ai_pos < router_pos):
        return _fail('nav order must be Memory, Brokers, AI Hub, Router')

    if 'Open External' not in src:
        return _fail('Open External missing')

    if 'renderSourceFeed' not in src:
        return _fail('internal renderSourceFeed handler missing')

    if '/api/debug/source-feed' not in src:
        return _fail('must use internal source feed API')

    if 'No cached items for this source yet. Use Refresh Source or Open External.' not in src:
        return _fail('empty state message missing')

    if 'clearPersistedSourceLanding' not in src:
        return _fail('must clear persisted source landing on load')

    if '#browserToolbar { display: none !important; }' not in src:
        return _fail('browser toolbar must stay hidden (no blocked iframe default)')

    print('FRONTEND_NO_DROPDOWN_REVERT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
