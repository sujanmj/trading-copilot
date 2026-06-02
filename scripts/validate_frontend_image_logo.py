#!/usr/bin/env python3
"""
Validate Stage 44Z image logo branding in frontend/index.html.

Prints exactly FRONTEND_IMAGE_LOGO_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
LOGO = PROJECT_ROOT / 'frontend' / 'assets' / 'astraedge-logo.png'


def _fail(msg: str) -> int:
    print(f'FRONTEND_IMAGE_LOGO_FAIL: {msg}', file=sys.stderr)
    return 1


def _section(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    end = src.find(end_marker, start)
    if start < 0 or end < 0:
        return ''
    return src[start:end]


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    if not LOGO.is_file():
        return _fail('frontend/assets/astraedge-logo.png missing')

    src = INDEX.read_text(encoding='utf-8')

    if 'GUI_BUILD_STAGE_44Z_IMAGE_LOGO_FIXED' not in src:
        return _fail('GUI_BUILD_STAGE_44Z_IMAGE_LOGO_FIXED marker missing')

    if 'astraedge-logo.png' not in src:
        return _fail('astraedge-logo.png reference missing')

    if 'astraedge-logo-img' not in src:
        return _fail('astraedge-logo-img class missing')

    if 'brand-fallback' not in src:
        return _fail('brand-fallback missing')

    if 'header-grid' not in src:
        return _fail('header-grid missing')

    brand = _section(src, 'class="brand-block"', 'class="header-main-line"')
    if not brand:
        return _fail('brand-block missing')

    if 'astraedge-logo-img' not in brand:
        return _fail('astraedge-logo-img must appear in brand-block')

    if 'brand-fallback' not in brand:
        return _fail('brand-fallback must appear in brand-block')

    if 'astra-logo-mark' in brand:
        return _fail('legacy astra-logo-mark must not remain in brand-block')

    header_start = src.find('<header class="app-header"')
    header_end = src.find('</header>', header_start)
    if header_start < 0 or header_end < 0:
        return _fail('app-header block missing')
    header = src[header_start:header_end]

    main_line = _section(header, 'class="header-main-line"', 'class="brand-spacer"')
    status_line = _section(header, 'class="header-status-line"', '</div>')
    if not main_line or not status_line:
        return _fail('header-main-line and header-status-line required')

    for label in ('BROKERS:', 'NEWS:', 'AI:'):
        if label not in main_line:
            return _fail(f'{label} must appear in header-main-line')

    mem_pos = main_line.find('memoryNavBtn')
    brokers_pos = main_line.find('brokersNavBtn')
    ai_pos = main_line.find('aiHubNavBtn')
    router_pos = main_line.find('routerNavBtn')
    if not (mem_pos < brokers_pos < ai_pos < router_pos):
        return _fail('Memory, Brokers, AI Hub, Router order required in header-main-line')

    if 'routerNavBtn' in status_line:
        return _fail('Router must not appear in header-status-line')

    for token in ('reviewBtn', 'aiOpsBtn', 'apiStatus', 'guiModeBadge', 'live-badge'):
        if token not in status_line:
            return _fail(f'status control missing from header-status-line: {token!r}')

    for fn in ('renderSourceFeed', '/api/debug/source-feed'):
        if fn not in src:
            return _fail(f'source feed wiring missing: {fn!r}')

    print('FRONTEND_IMAGE_LOGO_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
