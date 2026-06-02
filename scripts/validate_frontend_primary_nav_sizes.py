#!/usr/bin/env python3
"""
Validate Stage 44E primary nav alignment — Memory / Brokers / AI Hub / Router.

Prints exactly FRONTEND_PRIMARY_NAV_SIZES_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_PRIMARY_NAV_SIZES_FAIL: {msg}', file=sys.stderr)
    return 1


def _topbar(src: str) -> str:
    match = re.search(r'<div class="topbar">([\s\S]*?)</div>\s*<div class="main"', src)
    return match.group(1) if match else ''


def _button_classes(topbar: str, btn_id: str) -> str:
    pattern = re.compile(
        rf'<button[^>]*id="{re.escape(btn_id)}"[^>]*class="([^"]+)"',
        re.IGNORECASE,
    )
    match = pattern.search(topbar)
    if match:
        return match.group(1)
    pattern2 = re.compile(
        rf'<button[^>]*class="([^"]+)"[^>]*id="{re.escape(btn_id)}"',
        re.IGNORECASE,
    )
    match2 = pattern2.search(topbar)
    return match2.group(1) if match2 else ''


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')
    topbar = _topbar(src)
    if not topbar:
        return _fail('topbar block missing')

    if '<details class="brokers-menu"' not in src:
        return _fail('BROKERS dropdown (<details class="brokers-menu">) missing')

    if '<details class="news-menu"' not in src:
        return _fail('NEWS dropdown (<details class="news-menu">) missing')

    if 'topbar-left' not in src:
        return _fail('topbar-left cluster required for single-row nav layout')

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

    if 'AstraEdge AI' not in topbar:
        return _fail('header must show AstraEdge AI branding')

    mem_pos = topbar.find('memoryNavBtn')
    brokers_pos = topbar.find('brokersNavBtn')
    ai_pos = topbar.find('aiHubNavBtn')
    router_pos = topbar.find('routerNavBtn')
    if not (mem_pos < brokers_pos < ai_pos < router_pos):
        return _fail('nav order must be Memory, Brokers, AI Hub, Router')

    for btn_id in ('memoryNavBtn', 'brokersNavBtn', 'aiHubNavBtn', 'routerNavBtn'):
        classes = _button_classes(topbar, btn_id)
        if 'primary-nav-btn' not in classes:
            return _fail(f'{btn_id} must use primary-nav-btn')

    mem_classes = _button_classes(topbar, 'memoryNavBtn')
    brokers_classes = _button_classes(topbar, 'brokersNavBtn')
    ai_classes = _button_classes(topbar, 'aiHubNavBtn')
    if mem_classes != brokers_classes or mem_classes != ai_classes:
        return _fail('Memory, Brokers, AI Hub must share identical nav classes')

    if '.primary-nav-btn' not in src:
        return _fail('.primary-nav-btn shared style rule missing')

    if 'topbar-right-cluster' in src or 'topbar-primary-nav' in src:
        return _fail('experimental nav wrappers must be removed')

    print('FRONTEND_PRIMARY_NAV_SIZES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
