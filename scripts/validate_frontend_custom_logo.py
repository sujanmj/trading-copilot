#!/usr/bin/env python3
"""
Validate Stage 44Y custom inline AstraEdge AI logo mark.

Prints exactly FRONTEND_CUSTOM_LOGO_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_CUSTOM_LOGO_FAIL: {msg}', file=sys.stderr)
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

    src = INDEX.read_text(encoding='utf-8')

    if 'GUI_BUILD_STAGE_44Y_CUSTOM_LOGO_MARK' not in src:
        return _fail('GUI_BUILD_STAGE_44Y_CUSTOM_LOGO_MARK marker missing')

    if 'astra-logo-mark' not in src:
        return _fail('astra-logo-mark class missing')

    brand = _section(src, 'class="brand-block"', 'class="header-main-line"')
    if not brand:
        return _fail('brand-block missing')

    if '<svg' not in brand or 'astra-logo-mark' not in brand:
        return _fail('inline svg logo must exist in brand-block')

    if 'AstraEdge AI' not in brand:
        return _fail('AstraEdge AI text missing in brand-block')

    if re.search(r'src=["\']https?://[^"\']+design\.com', src, re.I):
        return _fail('must not use external design.com image URL')

    if re.search(r'src=["\']https?://[^"\']+\.(png|jpg|jpeg|webp|gif)', brand, re.I):
        return _fail('brand-block must not use remote raster logo image')

    for cls in ('astra-logo-hex', 'astra-logo-circuit', 'astra-logo-core'):
        if cls not in src:
            return _fail(f'logo style class missing: {cls!r}')

    if 'renderSourceFeed' not in src or '/api/debug/source-feed' not in src:
        return _fail('source feed wiring missing')

    if 'id="brokerSourceRow"' not in src or 'id="newsSourceRow"' not in src:
        return _fail('broker/news source groups missing')

    if 'header-grid' not in src or 'header-main-line' not in src:
        return _fail('header grid layout missing')

    print('FRONTEND_CUSTOM_LOGO_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
