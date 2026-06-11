#!/usr/bin/env python3
"""Unit tests — standalone My Feed workspace has no image thumbnails (Stage 50H)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'GUI_MY_FEED_NO_THUMBNAIL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')

    for needle in (
        'myFeedNavBtn',
        'myFeedMainContent',
        'async function loadMyFeedMain',
        '/api/myfeed',
        'Text-only market feed',
    ):
        if needle not in src:
            return _fail(f'index.html missing standalone My Feed marker {needle!r}')

    if re.search(r'data-tab=["\']myfeed["\']', src):
        return _fail('My Feed must not be an AI Hub tab (standalone workspace only)')
    if 'renderMyFeedAihubHtml' in src or 'function loadMyFeed(' in src:
        return _fail('AI Hub My Feed render/load helpers must be removed')

    if re.search(r'data-tab=["\']reddit["\']', src):
        return _fail('AI Hub must not expose reddit tab')
    if 'reddit: loadReddit' in src.replace(' ', ''):
        return _fail('TAB_PANEL_LOADERS must not wire loadReddit')

    start = src.find('async function loadMyFeedMain')
    end = src.find('window.loadMyFeedMain = loadMyFeedMain', start)
    if start < 0 or end < 0:
        return _fail('could not locate standalone My Feed render block')
    block = src[start:end]
    if re.search(r'<img\b', block, re.I):
        return _fail('standalone My Feed render must not use img tags')
    if 'thumbnail' in block.lower():
        return _fail('standalone My Feed render must not mention thumbnails')

    print('GUI_MY_FEED_NO_THUMBNAIL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
