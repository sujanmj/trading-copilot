#!/usr/bin/env python3
"""Unit tests — My Feed screenshot OCR stores text only (Stage 50B)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FORBIDDEN_KEYS = frozenset({'image_path', 'base64', 'filename', 'image_bytes', 'screenshot_path'})


def _fail(msg: str) -> int:
    print(f'MYFEED_SCREENSHOT_OCR_TEXT_ONLY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _assert_no_image_fields(payload: dict, *, label: str) -> int | None:
    for key in FORBIDDEN_KEYS:
        if key in payload:
            return _fail(f'{label} must not include {key!r}')
    blob = json.dumps(payload).lower()
    for token in ('base64', 'image/png', '/tmp/', '.png'):
        if token in blob and token != '.png':
            return _fail(f'{label} leaked image artifact {token!r}')
    return None


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        fake_ocr = {
            'ok': True,
            'text': 'NIFTY opens higher on strong global cues across banking sector today',
            'cleaned_summary': 'NIFTY opens higher on strong global cues across banking sector today',
            'confidence': 0.85,
            'extracted': {},
            'error': '',
        }
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            with patch('backend.my_feed.image_extraction.extract_market_text_from_image_bytes', return_value=fake_ocr):
                from backend.my_feed.feed_processor import ingest_screenshot_bytes, sanitize_item_for_api
                from backend.my_feed.my_feed_db import get_item

                result = ingest_screenshot_bytes(b'\x89PNGfake', source='gui_screenshot')
                if not result.get('ok'):
                    return _fail(f'screenshot ingest failed: {result!r}')

                record = result.get('record') or {}
                feed_id = record.get('feed_id')
                if not feed_id:
                    return _fail('missing feed_id from screenshot ingest')

                for payload, label in (
                    (record, 'ingest record'),
                    (get_item(feed_id) or {}, 'sqlite row'),
                    (sanitize_item_for_api({**record, 'image_path': '/secret.png', 'base64': 'abc', 'filename': 'x.png'}), 'api item'),
                ):
                    err = _assert_no_image_fields(payload, label=label)
                    if err:
                        return err

                conn = sqlite3.connect(str(db_path))
                try:
                    row = conn.execute('SELECT payload FROM feed_items WHERE feed_id = ?', (feed_id,)).fetchone()
                    payload_text = str((row or [''])[0] or '').lower()
                    for token in ('image_path', 'base64', 'filename'):
                        if token in payload_text:
                            return _fail(f'sqlite payload must not persist {token!r}')
                finally:
                    conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_SCREENSHOT_OCR_TEXT_ONLY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
