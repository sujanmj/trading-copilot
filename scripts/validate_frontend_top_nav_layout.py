#!/usr/bin/env python3
"""
Validate stable Trading Copilot top nav — full visible links, AI Hub beside Brokers.

Prints exactly FRONTEND_TOP_NAV_LAYOUT_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_TOP_NAV_LAYOUT_FAIL: {msg}', file=sys.stderr)
    return 1


def _topbar(src: str) -> str:
    match = re.search(r'<div class="topbar">([\s\S]*?)</div>\s*<div class="main"', src)
    return match.group(1) if match else ''


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')
    topbar = _topbar(src)
    if not topbar:
        return _fail('topbar block missing')

    if '⚡ Trading Copilot' not in topbar:
        return _fail('Trading Copilot branding must be visible in topbar')

    if '<details class="news-menu"' in src:
        return _fail('NEWS must not be dropdown-only')

    required_labels = (
        'Angel', 'Zerodha', 'Groww', 'Upstox', 'IndMoney', '💼 Portfolio',
        'BROKERS:', 'NEWS:', 'MC', 'ET', 'Mint', 'NDTV', '📱 Inshorts',
        '🤖 Reddit', 'ET Now', 'CNBC', 'NSE',
        '🧠 Memory', '🏦 Brokers', '🤖 AI Hub', '🌍 Router',
        'REVIEW', 'OPS', 'WEB LOCAL', '🔴 LIVE',
    )
    for label in required_labels:
        if label not in topbar:
            return _fail(f'missing visible nav label: {label!r}')

    mem_pos = topbar.find('memoryNavBtn')
    brokers_pos = topbar.find('brokersNavBtn')
    ai_pos = topbar.find('aiHubNavBtn')
    router_pos = topbar.find('routerNavBtn')
    if not (mem_pos < brokers_pos < ai_pos < router_pos):
        return _fail('nav order must be Memory, Brokers, AI Hub, Router')

    if 'right-status' not in topbar:
        return _fail('right-status cluster missing')

    if 'topbar-right-cluster' in src or 'topbar-primary-nav' in src:
        return _fail('experimental nav wrappers must be removed')

    if 'margin-left: auto' not in src:
        return _fail('right-status auto margin missing')

    print('FRONTEND_TOP_NAV_LAYOUT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
