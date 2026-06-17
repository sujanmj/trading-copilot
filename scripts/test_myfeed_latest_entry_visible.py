#!/usr/bin/env python3
"""Stage 50X — newest /feed item appears at top of /myfeed list."""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_LATEST_ENTRY_VISIBLE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.cache_invalidation import load_myfeed_items_for_telegram
    from backend.my_feed.feed_processor import ingest_text, list_feed_items

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=[]):
            ingest_text('older generic market headline about banking sector', source='telegram_text')
            time.sleep(0.05)
            latest = ingest_text('adani lost airport contract to kenya', source='telegram_text')
            items = list_feed_items(limit=5)
            telegram_items = load_myfeed_items_for_telegram(limit=5, force_refresh=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    record = latest.get('record') or {}
    feed_id = str(record.get('feed_id') or '')
    if not feed_id:
        return _fail('latest feed must persist feed_id')
    if not items or str(items[0].get('feed_id')) != feed_id:
        return _fail('newest feed must sort first by created_at')
    if not telegram_items or str(telegram_items[0].get('feed_id')) != feed_id:
        return _fail('telegram list loader must show newest feed first')

    print('MYFEED_LATEST_ENTRY_VISIBLE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
