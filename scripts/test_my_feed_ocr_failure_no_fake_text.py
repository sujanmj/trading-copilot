#!/usr/bin/env python3
"""Unit tests — OCR failure must not hallucinate text (Stage 50A)."""

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
    print(f'MY_FEED_OCR_FAILURE_NO_FAKE_TEXT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.feed_processor import ingest_screenshot_bytes
            from backend.my_feed.my_feed_db import list_items

            with patch(
                'backend.my_feed.screenshot_ocr.extract_text_from_image_bytes',
                return_value={'ok': False, 'text': '', 'confidence': 0.0, 'error': 'low_confidence'},
            ):
                result = ingest_screenshot_bytes(b'bytes')
            if result.get('ok'):
                return _fail('OCR failure must not succeed')
            reply = str(result.get('reply') or '')
            if 'MY_FEED_NEEDS_TEXT' not in reply:
                return _fail('missing MY_FEED_NEEDS_TEXT reply')
            if 'NIFTY' in reply or 'SENSEX' in reply:
                return _fail('must not hallucinate market text on OCR failure')
            if list_items(limit=5):
                return _fail('must not store feed item on OCR failure')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MY_FEED_OCR_FAILURE_NO_FAKE_TEXT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
