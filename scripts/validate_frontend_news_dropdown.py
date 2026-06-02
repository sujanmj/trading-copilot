#!/usr/bin/env python3
"""
Validate Stage 44H NEWS dropdown in top nav.

Prints exactly FRONTEND_NEWS_DROPDOWN_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_NEWS_DROPDOWN_FAIL: {msg}', file=sys.stderr)
    return 1


def _topbar(src: str) -> str:
    match = re.search(r'<div class="topbar">([\s\S]*?)</div>\s*<div class="main"', src)
    return match.group(1) if match else ''


def _news_panel(src: str) -> str:
    match = re.search(
        r'<details class="news-menu">([\s\S]*?)</details>',
        src,
        re.IGNORECASE,
    )
    return match.group(1) if match else ''


def main() -> int:
    for path in (INDEX, WORKSPACE):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    src = INDEX.read_text(encoding='utf-8')
    topbar = _topbar(src)
    if not topbar:
        return _fail('topbar block missing')

    if '<details class="news-menu"' not in src:
        return _fail('NEWS dropdown (<details class="news-menu">) missing')

    panel = _news_panel(src)
    if not panel:
        return _fail('news-menu panel missing')

    required_news = (
        ('MC', 'data-source="MC"'),
        ('ET', 'data-source="ET"'),
        ('Mint', 'data-source="Mint"'),
        ('NDTV', 'data-source="NDTV"'),
        ('Inshorts', 'data-source="Inshorts"'),
        ('Reddit', 'data-source="Reddit"'),
        ('ET Now', 'data-source="ET Now"'),
        ('CNBC', 'data-source="CNBC"'),
        ('NSE', 'data-source="NSE"'),
    )
    for label, token in required_news:
        if token not in panel:
            return _fail(f'NEWS dropdown missing {label!r} with data-source')

    brokers_match = re.search(
        r'<details class="brokers-menu">([\s\S]*?)</details>',
        src,
        re.IGNORECASE,
    )
    brokers_panel = brokers_match.group(1) if brokers_match else ''
    if not brokers_panel:
        return _fail('brokers-menu panel missing')

    for broker in ('Angel', 'Zerodha', 'Groww', 'Upstox', 'IndMoney', 'Portfolio'):
        if f'data-source="{broker}"' not in brokers_panel:
            return _fail(f'broker button {broker!r} must be inside BROKERS dropdown')
        if f'data-source="{broker}"' in panel:
            return _fail(f'broker button {broker!r} must not be inside NEWS dropdown')

    if 'BROKERS:' not in topbar:
        return _fail('BROKERS label must remain visible in topbar')

    for btn_id in ('memoryNavBtn', 'brokersNavBtn', 'aiHubNavBtn', 'routerNavBtn'):
        if btn_id not in topbar:
            return _fail(f'{btn_id} must remain visible in top nav')

    mem_pos = topbar.find('memoryNavBtn')
    brokers_pos = topbar.find('brokersNavBtn')
    ai_pos = topbar.find('aiHubNavBtn')
    router_pos = topbar.find('routerNavBtn')
    if not (mem_pos < brokers_pos < ai_pos < router_pos):
        return _fail('nav order must be Memory, Brokers, AI Hub, Router')

    workspace_src = WORKSPACE.read_text(encoding='utf-8')
    if '.news-btn' not in workspace_src or 'closest(' not in workspace_src:
        return _fail('WorkspaceManager must delegate clicks on .news-btn inside dropdown')

    print('FRONTEND_NEWS_DROPDOWN_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
