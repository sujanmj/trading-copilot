#!/usr/bin/env python3
"""Unit tests — GUI My Feed clipboard image paste (Stage 50B)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'GUI_MYFEED_CLIPBOARD_IMAGE_PASTE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    anchor = html.find('loadMyFeedMain')
    if anchor < 0:
        return _fail('frontend/index.html missing loadMyFeedMain')
    section = html[anchor:anchor + 6000]

    for needle in (
        "addEventListener('paste'",
        'clipboardData',
        "item.type.startsWith('image/')",
        "e.preventDefault()",
        "'/api/myfeed/screenshot'",
        'uploadScreenshotFile',
        "method: 'POST'",
    ):
        if needle not in section:
            return _fail(f'My Feed paste handler missing {needle!r}')

    paste_block = section[section.find("addEventListener('paste'"):]
    if "uploadScreenshotFile" not in paste_block or "'/api/myfeed/screenshot'" not in section:
        return _fail('paste handler must route clipboard images through /api/myfeed/screenshot upload')

    print('GUI_MYFEED_CLIPBOARD_IMAGE_PASTE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
