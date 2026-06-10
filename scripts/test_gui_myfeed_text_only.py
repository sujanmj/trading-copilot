#!/usr/bin/env python3
"""Stage 50G — GUI My Feed text-only."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'GUI_MYFEED_TEXT_ONLY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    if 'myFeedScreenshotInput' in html:
        return _fail('GUI must not include screenshot file input')
    if 'uploadScreenshotFile' in html:
        return _fail('GUI must not include screenshot upload handler')
    if '/api/myfeed/screenshot' in html:
        return _fail('GUI must not call screenshot API')
    if 'Text-only market feed. Paste news text here.' not in html:
        return _fail('GUI must show text-only copy')
    if 'myFeedTextSubmit' not in html or 'myFeedTextInput' not in html:
        return _fail('GUI must keep text input and Save Text button')
    if "alert('My Feed save failed" in html:
        return _fail('GUI should use inline status instead of alert for save failures')

    print('GUI_MYFEED_TEXT_ONLY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
