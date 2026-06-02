#!/usr/bin/env python3
"""
Validate Stage 44AC — black header background and internal source app pages.

Prints exactly FRONTEND_BLACK_HEADER_SOURCE_APPS_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_BLACK_HEADER_SOURCE_APPS_FAIL: {msg}', file=sys.stderr)
    return 1


def _function_body(src: str, name: str) -> str:
    match = re.search(rf'(?:async\s+)?function {re.escape(name)}\([^)]*\)\s*\{{', src)
    if not match:
        return ''
    start = match.end()
    depth = 1
    i = start
    while i < len(src) and depth:
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
        i += 1
    return src[start:i - 1]


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')

    if 'GUI_BUILD_STAGE_44AC_BLACK_HEADER_SOURCE_APPS' not in src:
        return _fail('GUI_BUILD_STAGE_44AC_BLACK_HEADER_SOURCE_APPS marker missing')

    header_block = src[src.find('.app-header'):src.find('.broker-placeholder')]
    if not re.search(r'background:\s*#000\s*!important', header_block):
        return _fail('header/main/logo row must use background #000 !important')

    if 'astraedge-logo-wide.png' not in src:
        return _fail('astraedge-logo-wide.png not referenced')

    if 'renderSourceFeed' not in src:
        return _fail('renderSourceFeed missing')

    if 'ASTRA_SOURCE_META' not in src:
        return _fail('ASTRA_SOURCE_META map missing')

    for key in ('Angel', 'Zerodha', 'MC', 'ET', 'NSE', 'Portfolio'):
        if key not in src:
            return _fail(f'source metadata entry missing: {key!r}')

    if 'source-empty-state-card' not in src:
        return _fail('source empty state card class missing')

    if 'sfv-status-card' not in src or 'Cached items' not in src:
        return _fail('cached item count/status card missing')

    for token in ('Open External', 'Refresh Source', 'Back to Dashboard'):
        if token not in src:
            return _fail(f'missing UI token: {token}')

    render_body = _function_body(src, 'renderSourceFeed')
    if not render_body:
        return _fail('renderSourceFeed body missing')

    if re.search(r'<iframe\b', render_body, re.IGNORECASE):
        return _fail('renderSourceFeed must not embed iframe for source loading')

    if re.search(r'window\.open\s*\(', render_body):
        return _fail('renderSourceFeed must not auto window.open')

    bind_body = _function_body(src, 'bindAstraSourceItemClick')
    if bind_body and re.search(r'window\.open\s*\(', bind_body):
        return _fail('source click handler must not auto window.open')

    if bind_body and 'iframe' in bind_body.lower():
        return _fail('source click handler must not embed iframe')

    if 'refresh=1' not in src:
        return _fail('Refresh Source must try refresh=1 endpoint')

    if 'Refreshing…' not in src and 'Refreshing...' not in src:
        return _fail('Refreshing state text missing')

    print('FRONTEND_BLACK_HEADER_SOURCE_APPS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
