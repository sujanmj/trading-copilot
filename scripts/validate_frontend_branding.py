#!/usr/bin/env python3
"""
Validate visible frontend branding — Trading Copilot.

Prints exactly FRONTEND_BRANDING_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
MAIN = PROJECT_ROOT / 'frontend' / 'main.js'
PACKAGE = PROJECT_ROOT / 'frontend' / 'package.json'


def _fail(msg: str) -> int:
    print(f'FRONTEND_BRANDING_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (INDEX, MAIN, PACKAGE):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    main_src = MAIN.read_text(encoding='utf-8')
    package_src = PACKAGE.read_text(encoding='utf-8')

    if 'Trading Copilot' not in index_src:
        return _fail('index.html missing Trading Copilot branding')

    title_match = re.search(r'<title>\s*([^<]+)\s*</title>', index_src, re.IGNORECASE)
    if not title_match or title_match.group(1).strip() != 'Trading Copilot':
        return _fail('document title must be Trading Copilot')

    if '⚡ Trading Copilot' not in index_src:
        return _fail('header logo text must be ⚡ Trading Copilot')

    if 'AstraEdge AI' in index_src:
        return _fail('index.html must not contain AstraEdge AI branding')

    if "title: 'Trading Copilot'" not in main_src.replace('"', "'"):
        return _fail('Electron window title must be Trading Copilot')

    if 'Trading Copilot' not in package_src:
        return _fail('package.json description should mention Trading Copilot')

    print('FRONTEND_BRANDING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
