#!/usr/bin/env python3
"""Unit tests — My Feed OCR failure inline response (Stage 50D)."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_OCR_FAILURE_INLINE_RESPONSE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        fake_ocr = {
            'ok': False,
            'text': '',
            'notifications': [],
            'ignored_private_count': 0,
            'needs_text': True,
            'error': 'low_confidence',
            'extracted': {},
        }
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            with patch('backend.my_feed.image_extraction.extract_market_text_from_image_bytes', return_value=fake_ocr):
                from backend.my_feed.feed_processor import ingest_screenshot_bytes, format_needs_text_reply
                from backend.my_feed.my_feed_db import list_items

                result = ingest_screenshot_bytes(b'\x89PNGfake', source='gui_screenshot')
                if result.get('ok'):
                    return _fail('OCR failure must not succeed')
                reply = str(result.get('reply') or '')
                if 'MY_FEED_NEEDS_TEXT' not in reply:
                    return _fail('missing MY_FEED_NEEDS_TEXT reply')
                message = str(result.get('message') or '')
                if 'Could not read market news' not in message:
                    return _fail(f'missing inline failure message, got {message!r}')
                if list_items(limit=5):
                    return _fail('must not store feed item on OCR failure')
                if format_needs_text_reply() != reply:
                    return _fail('reply must match format_needs_text_reply()')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_OCR_FAILURE_INLINE_RESPONSE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
