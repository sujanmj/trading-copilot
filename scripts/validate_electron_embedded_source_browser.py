#!/usr/bin/env python3
"""
Validate Stage 44AD — Electron embedded source browser in frontend GUI.

Prints exactly ELECTRON_EMBEDDED_SOURCE_BROWSER_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
MAIN = PROJECT_ROOT / 'frontend' / 'main.js'


def _fail(msg: str) -> int:
    print(f'ELECTRON_EMBEDDED_SOURCE_BROWSER_FAIL: {msg}', file=sys.stderr)
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
    for path in (INDEX, MAIN):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    main_src = MAIN.read_text(encoding='utf-8')

    if 'GUI_BUILD_STAGE_44AD_ELECTRON_EMBEDDED_SOURCE_BROWSER' not in index_src and 'GUI_BUILD_STAGE_44AE_WEB_EXTERNAL_SOURCES' not in index_src:
        return _fail('GUI_BUILD_STAGE_44AD/44AE marker missing')

    if 'renderEmbeddedSourceBrowser' not in index_src:
        return _fail('renderEmbeddedSourceBrowser missing in index.html')

    if 'ASTRA_IS_ELECTRON' not in index_src:
        return _fail('ASTRA_IS_ELECTRON detection missing')

    if 'window.electronAPI' not in index_src and 'electronAPI' not in index_src:
        return _fail('Electron detection must reference window.electronAPI')

    if 'navigator.userAgent.toLowerCase().includes' not in index_src:
        return _fail('Electron detection must check navigator.userAgent')

    bind_body = _function_body(index_src, 'bindAstraSourceItemClick')
    if not bind_body:
        return _fail('bindAstraSourceItemClick missing')

    if 'ASTRA_IS_ELECTRON' not in bind_body and 'astraOpenSourceItem' not in bind_body:
        return _fail('source click handler must branch electron vs browser')

    open_body = _function_body(index_src, 'astraOpenSourceItem')
    if not open_body:
        return _fail('astraOpenSourceItem missing')

    if 'renderEmbeddedSourceBrowser' not in open_body:
        return _fail('electron path must call renderEmbeddedSourceBrowser')

    if 'renderSourceFeed' not in open_body:
        web_body = _function_body(index_src, 'astraOpenWebExternalSource')
        if not web_body or 'window.open' not in web_body:
            return _fail('browser path must call window.open via astraOpenWebExternalSource')

    embedded_body = _function_body(index_src, 'renderEmbeddedSourceBrowser')
    if not embedded_body:
        return _fail('renderEmbeddedSourceBrowser body missing')

    if 'astraSourceWebview' not in embedded_body and 'astraSourceWebview' not in index_src:
        return _fail('webview id astraSourceWebview missing')

    if '<webview' not in index_src:
        return _fail('webview tag missing in index.html')

    for token in ('Back', 'Forward', 'Reload', 'Open External', 'Back to Dashboard'):
        if token not in embedded_body:
            return _fail(f'embedded toolbar missing: {token!r}')

    feed_body = _function_body(index_src, 'renderSourceFeed')
    if not feed_body:
        return _fail('renderSourceFeed body missing')

    for token in ('astraEmbeddedBackBtn', 'astraEmbeddedForwardBtn', 'astraEmbeddedReloadBtn'):
        if token in feed_body:
            return _fail('Back/Forward/Reload toolbar must not appear in browser renderSourceFeed')

    if 'Open External' not in feed_body:
        return _fail('browser mode renderSourceFeed must retain Open External')

    if 'renderSourceFeed' not in index_src:
        return _fail('renderSourceFeed must remain for browser mode')

    if 'webviewTag' not in main_src or 'true' not in main_src.split('webviewTag')[1][:20]:
        return _fail('Electron main must set webviewTag: true')

    if re.search(r'nodeIntegration\s*:\s*true', main_src):
        return _fail('Electron main must not set nodeIntegration: true')

    if 'contextIsolation' not in main_src or not re.search(r'contextIsolation\s*:\s*true', main_src):
        return _fail('Electron main must set contextIsolation: true')

    if 'Embedded browser unavailable. Use Open External.' not in index_src:
        return _fail('embedded fallback message missing')

    print('ELECTRON_EMBEDDED_SOURCE_BROWSER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
