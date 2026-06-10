#!/usr/bin/env python3
"""Unit tests — My Feed market text stored in SQLite (Stage 50A)."""

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
    print(f'MY_FEED_MARKET_TEXT_STORED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.feed_processor import ingest_text
            from backend.my_feed.my_feed_db import list_items

            text = 'Reliance Industries Q4 results beat estimates; stock in focus for NIFTY today'
            result = ingest_text(text, source='telegram_text')
            if not result.get('ok'):
                return _fail(f'ingest failed: {result!r}')
            reply = str(result.get('reply') or '')
            if 'MY_FEED_SAVED' not in reply:
                return _fail('missing MY_FEED_SAVED reply')
            record = result.get('record') or {}
            for key in (
                'feed_id', 'created_at', 'source', 'cleaned_summary',
                'suggested_action', 'impact_score', 'status',
            ):
                if key not in record:
                    return _fail(f'missing stored field {key}')
            if record.get('source') != 'telegram_text':
                return _fail('wrong source stored')
            if 'image_path' in record:
                return _fail('image_path must not be stored')
            if not list_items(limit=1):
                return _fail('item not persisted')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MY_FEED_MARKET_TEXT_STORED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
