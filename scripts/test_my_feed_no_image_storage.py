#!/usr/bin/env python3
"""Unit tests — My Feed never stores image paths (Stage 50A)."""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MY_FEED_NO_IMAGE_STORAGE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.feed_processor import ingest_text, sanitize_item_for_api
            from backend.my_feed.my_feed_db import get_item, init_my_feed_db

            init_my_feed_db()
            result = ingest_text(
                'NIFTY surges on strong FII inflows\nRELIANCE results beat estimates',
                source='telegram_text',
            )
            if not result.get('ok'):
                return _fail(f'ingest failed: {result!r}')
            record = result.get('record') or {}
            feed_id = record.get('feed_id')
            if not feed_id:
                return _fail('missing feed_id')

            stored = get_item(feed_id) or {}
            if 'image_path' in stored:
                return _fail('stored row must not include image_path key')

            public = sanitize_item_for_api({**stored, 'image_path': '/tmp/secret.png'})
            if 'image_path' in public:
                return _fail('sanitize_item_for_api must strip image_path')

            conn = sqlite3.connect(str(db_path))
            try:
                cols = [row[1] for row in conn.execute('PRAGMA table_info(feed_items)').fetchall()]
            finally:
                conn.close()
            if 'image_path' in cols:
                return _fail('feed_items schema must not have image_path column')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MY_FEED_NO_IMAGE_STORAGE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
