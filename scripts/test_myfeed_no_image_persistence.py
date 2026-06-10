#!/usr/bin/env python3
"""Unit tests — My Feed no image persistence (Stage 50B final)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_NO_IMAGE_PERSISTENCE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    db_src = (PROJECT_ROOT / 'backend/my_feed/my_feed_db.py').read_text(encoding='utf-8')
    if 'image_path' in db_src.lower() and 'pop(\'image_path\'' not in db_src:
        return _fail('schema must not persist image_path')

    processor = (PROJECT_ROOT / 'backend/my_feed/feed_processor.py').read_text(encoding='utf-8')
    extraction = (PROJECT_ROOT / 'backend/my_feed/image_extraction.py').read_text(encoding='utf-8')
    ocr = (PROJECT_ROOT / 'backend/my_feed/screenshot_ocr.py').read_text(encoding='utf-8')

    if 'sanitize_item_for_api' not in processor:
        return _fail('feed_processor must sanitize API items')
    if 'os.remove' not in extraction or 'finally' not in extraction:
        return _fail('image_extraction must delete temp file in finally block')
    if 'extract_market_text_from_image_bytes' not in ocr:
        return _fail('screenshot_ocr must delegate to shared image_extraction helper')
    if 'image_path' not in processor:
        return _fail('processor must strip image_path from API payload')

    html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    if 'myfeed-card' in html and '<img' in html[html.find('myfeed-card'):html.find('myfeed-card') + 800]:
        return _fail('My Feed card must not render image thumbnails')

    print('MYFEED_NO_IMAGE_PERSISTENCE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
