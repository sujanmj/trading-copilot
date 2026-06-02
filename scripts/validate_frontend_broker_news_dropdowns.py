#!/usr/bin/env python3
"""
Validate Stage 44I BROKERS + NEWS dropdowns in top nav.

Prints exactly FRONTEND_BROKER_NEWS_DROPDOWNS_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_BROKER_NEWS_DROPDOWNS_FAIL: {msg}', file=sys.stderr)
    return 1


def _topbar(src: str) -> str:
    match = re.search(r'<div class="topbar">([\s\S]*?)</div>\s*<div class="main"', src)
    return match.group(1) if match else ''


def _panel(src: str, menu_class: str) -> str:
    match = re.search(
        rf'<details class="{re.escape(menu_class)}">([\s\S]*?)</details>',
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

    if '<details class="brokers-menu"' not in src:
        return _fail('BROKERS dropdown (<details class="brokers-menu">) missing')

    if '<details class="news-menu"' not in src:
        return _fail('NEWS dropdown (<details class="news-menu">) missing')

    if '.brokers-menu-panel' not in src or '.brokers-menu-summary' not in src:
        return _fail('brokers-menu CSS (summary/panel) missing')

    brokers_panel = _panel(src, 'brokers-menu')
    news_panel = _panel(src, 'news-menu')
    if not brokers_panel:
        return _fail('brokers-menu panel missing')
    if not news_panel:
        return _fail('news-menu panel missing')

    required_brokers = (
        ('Angel', 'data-source="Angel"'),
        ('Zerodha', 'data-source="Zerodha"'),
        ('Groww', 'data-source="Groww"'),
        ('Upstox', 'data-source="Upstox"'),
        ('IndMoney', 'data-source="IndMoney"'),
        ('Portfolio', 'data-source="Portfolio"'),
    )
    for label, token in required_brokers:
        if token not in brokers_panel:
            return _fail(f'BROKERS dropdown missing {label!r} with data-source')
        if f'data-url=' not in brokers_panel:
            return _fail('broker dropdown items must include data-url')

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
        if token not in news_panel:
            return _fail(f'NEWS dropdown missing {label!r} with data-source')

    topbar_without_brokers_dropdown = re.sub(
        r'<details class="brokers-menu">[\s\S]*?</details>',
        '',
        topbar,
        count=1,
        flags=re.IGNORECASE,
    )
    if 'class="broker-btn"' in topbar_without_brokers_dropdown:
        return _fail('flat broker buttons must not appear outside BROKERS dropdown')

    if 'topbar-left' not in src:
        return _fail('topbar-left cluster missing for single-row layout')

    if 'BROKERS:' not in topbar or 'NEWS:' not in topbar:
        return _fail('BROKERS and NEWS labels must remain visible in topbar')

    workspace_src = WORKSPACE.read_text(encoding='utf-8')
    if '.broker-btn' not in workspace_src or 'closest(' not in workspace_src:
        return _fail('WorkspaceManager must delegate clicks on .broker-btn inside BROKERS dropdown')
    if '.news-btn' not in workspace_src:
        return _fail('WorkspaceManager must delegate clicks on .news-btn inside NEWS dropdown')
    if 'brokers-menu' not in workspace_src:
        return _fail('WorkspaceManager must close brokers-menu on item click')

    print('FRONTEND_BROKER_NEWS_DROPDOWNS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
