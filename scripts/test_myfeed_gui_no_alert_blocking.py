#!/usr/bin/env python3
"""Unit tests — My Feed GUI screenshot uses inline status not alert (Stage 50D)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_GUI_NO_ALERT_BLOCKING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    match = re.search(r'const uploadScreenshotFile = async \(file\) => \{.*?\n      \}', html, re.S)
    if not match:
        return _fail('uploadScreenshotFile block not found')
    block = match.group(0)
    if 'alert(' in block:
        return _fail('uploadScreenshotFile must not use alert()')
    for token in (
        'Extracting screenshot',
        'Could not read market news clearly',
        'myfeed-inline-status',
        'body.message',
        'saved_count',
    ):
        if token not in block:
            return _fail(f'uploadScreenshotFile missing inline UX token {token!r}')

    print('MYFEED_GUI_NO_ALERT_BLOCKING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
