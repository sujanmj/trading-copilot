#!/usr/bin/env python3
"""
Validate Stage 44AE — web mode opens external sources via window.open.

Prints exactly WEB_EXTERNAL_SOURCE_CLICKS_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'

REQUIRED_SOURCE_URLS = (
    'https://www.angelone.in/login/',
    'https://kite.zerodha.com/',
    'https://groww.in/',
    'https://login.upstox.com/',
    'https://www.indmoney.com/',
    'https://www.moneycontrol.com/',
    'https://economictimes.indiatimes.com/markets',
    'https://www.livemint.com/market',
    'https://www.ndtvprofit.com/',
    'https://inshorts.com/en/read/business',
    'https://www.reddit.com/r/IndianStockMarket/',
    'https://www.etnownews.com/markets',
    'https://www.cnbctv18.com/market/',
    'https://www.nseindia.com/',
)


def _fail(msg: str) -> int:
    print(f'WEB_EXTERNAL_SOURCE_CLICKS_FAIL: {msg}', file=sys.stderr)
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

    if 'GUI_BUILD_STAGE_44AE_WEB_EXTERNAL_SOURCES' not in src:
        return _fail('GUI_BUILD_STAGE_44AE_WEB_EXTERNAL_SOURCES marker missing')

    if '44AE' not in src:
        return _fail('boot log must mention 44AE')

    if 'ASTRA_SOURCE_META' not in src:
        return _fail('ASTRA_SOURCE_META map missing')

    for url in REQUIRED_SOURCE_URLS:
        if url not in src:
            return _fail(f'source URL map missing: {url!r}')

    open_body = _function_body(src, 'astraOpenSourceItem')
    if not open_body:
        return _fail('astraOpenSourceItem missing')

    if 'ASTRA_IS_ELECTRON' not in open_body:
        return _fail('astraOpenSourceItem must branch on ASTRA_IS_ELECTRON')

    if 'renderEmbeddedSourceBrowser' not in open_body:
        return _fail('electron path must call renderEmbeddedSourceBrowser')

    web_body = _function_body(src, 'astraOpenWebExternalSource')
    if not web_body:
        return _fail('astraOpenWebExternalSource missing for web mode routing')

    if "window.open(sourceUrl, '_blank', 'noopener,noreferrer')" not in web_body:
        if "window.open(" not in web_body or "'noopener,noreferrer'" not in web_body:
            return _fail('web mode must window.open external sources with noopener,noreferrer')

    if 'renderSourceFeed' in web_body:
        return _fail('web mode source click must not call renderSourceFeed')

    if 'renderSourceFeed' not in src:
        return _fail('renderSourceFeed must remain in index.html for Electron fallback')

    for token in ('astraedge-logo-wide.png', 'astraedge-logo-img', '.brand-block', '.header-grid'):
        if token not in src:
            return _fail(f'header/logo layout missing: {token!r}')

    print('WEB_EXTERNAL_SOURCE_CLICKS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
