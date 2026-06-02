#!/usr/bin/env python3
"""
Validate Stage 44D emergency UI revert — Trading Copilot stable layout restored.

Prints exactly FRONTEND_EMERGENCY_UI_REVERT_OK on success.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
MAIN = PROJECT_ROOT / 'frontend' / 'main.js'
PACKAGE = PROJECT_ROOT / 'frontend' / 'package.json'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_EMERGENCY_UI_REVERT_FAIL: {msg}', file=sys.stderr)
    return 1


def _topbar(src: str) -> str:
    match = re.search(r'<div class="topbar">([\s\S]*?)</div>\s*<div class="main"', src)
    return match.group(1) if match else ''


def main() -> int:
    for path in (INDEX, MAIN, PACKAGE, WORKSPACE):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    main_src = MAIN.read_text(encoding='utf-8')
    pkg = json.loads(PACKAGE.read_text(encoding='utf-8'))
    workspace_src = WORKSPACE.read_text(encoding='utf-8')
    topbar = _topbar(index_src)

    if not topbar:
        return _fail('topbar missing')

    if '⚡ Trading Copilot' not in topbar:
        return _fail('Trading Copilot header missing')

    if 'AstraEdge AI' in index_src:
        return _fail('AstraEdge AI must not appear in active frontend branding')

    if '<details class="news-menu"' in index_src or 'news-menu-panel' in index_src:
        return _fail('NEWS dropdown must be removed')

    if 'topbar-right-cluster' in index_src or 'topbar-quick-links' in index_src:
        return _fail('compressed nav wrappers must be removed')

    required = (
        'Angel', 'Zerodha', 'Groww', 'Upstox', 'IndMoney', '💼 Portfolio',
        'NEWS:', 'MC', 'ET', 'Mint', 'NDTV', '📱 Inshorts', '🤖 Reddit',
        'ET Now', 'CNBC', 'NSE',
        '🧠 Memory', '🏦 Brokers', '🤖 AI Hub', '🌍 Router',
        'REVIEW', 'OPS', 'WEB LOCAL', '🔴 LIVE',
    )
    for label in required:
        if label not in topbar:
            return _fail(f'missing visible nav label: {label!r}')

    mem = topbar.find('memoryNavBtn')
    brokers = topbar.find('brokersNavBtn')
    ai = topbar.find('aiHubNavBtn')
    router = topbar.find('routerNavBtn')
    if not (mem < brokers < ai < router):
        return _fail('Memory, Brokers, AI Hub must precede Router')

    scripts = pkg.get('scripts') or {}
    if str(scripts.get('start') or '') != 'electron .':
        return _fail('electron start script missing')
    if 'web' not in scripts or '5173' not in str(scripts.get('web') or ''):
        return _fail('browser web mode script missing')

    if 'Browser mode does not embed external sites here' not in workspace_src:
        return _fail('browser external-source placeholder behavior missing')

    if "title: 'Trading Copilot'" not in main_src.replace('"', "'"):
        return _fail('Electron window title must be Trading Copilot')

    print('FRONTEND_EMERGENCY_UI_REVERT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
