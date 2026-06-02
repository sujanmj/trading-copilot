#!/usr/bin/env python3
"""
Validate Stage 44F visible AstraEdge AI branding (UI only).

Prints exactly FRONTEND_ASTRAEDGE_BRANDING_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
MAIN = PROJECT_ROOT / 'frontend' / 'main.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_ASTRAEDGE_BRANDING_FAIL: {msg}', file=sys.stderr)
    return 1


def _topbar(src: str) -> str:
    match = re.search(r'<div class="topbar">([\s\S]*?)</div>\s*<div class="main"', src)
    return match.group(1) if match else ''


def main() -> int:
    for path in (INDEX, MAIN):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    main_src = MAIN.read_text(encoding='utf-8')
    topbar = _topbar(index_src)
    if not topbar:
        return _fail('topbar block missing')

    title_match = re.search(r'<title>\s*([^<]+)\s*</title>', index_src, re.IGNORECASE)
    if not title_match or title_match.group(1).strip() != 'AstraEdge AI':
        return _fail('document title must be AstraEdge AI')

    if '⚡ AstraEdge AI' not in topbar:
        return _fail('header logo text must be ⚡ AstraEdge AI')

    if '⚡ Astra</h1>' in topbar or '<title>Astra</title>' in index_src:
        return _fail('legacy Astra branding must not remain in visible UI')

    if "title: 'AstraEdge AI'" not in main_src.replace('"', "'"):
        return _fail('Electron window title must be AstraEdge AI')

    print('FRONTEND_ASTRAEDGE_BRANDING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
