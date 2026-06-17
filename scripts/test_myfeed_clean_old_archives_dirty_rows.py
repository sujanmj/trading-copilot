#!/usr/bin/env python3
"""Stage 50X — clean-old archives dirty CHAMBLERT/OCR rows and hides from default list."""

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
    print(f'MYFEED_CLEAN_OLD_ARCHIVES_DIRTY_ROWS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.clean_old import CLEAN_OLD_ARCHIVE_REASON, clean_old_my_feed_items
    from backend.my_feed.feed_processor import list_feed_items
    from backend.my_feed.my_feed_db import insert_feed_item, list_items

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            insert_feed_item({
                'source': 'telegram_screenshot',
                'raw_market_text': 'CHAMBLERT crude $72 mixed noise',
                'cleaned_summary': 'CHAMBLERT crude $72 mixed noise',
                'tickers': ['CHAMBLERT', 'INDIA', 'USA'],
                'themes': [],
                'sectors': [],
                'event_type': 'news',
                'sentiment': 'neutral',
                'impact_score': 40,
                'urgency': 'low',
                'suggested_action': 'NEWS ONLY',
                'status': 'active',
            })
            insert_feed_item({
                'source': 'telegram_text',
                'raw_market_text': 'clean verified style headline for TCS',
                'cleaned_summary': 'clean verified style headline for TCS',
                'tickers': ['TCS'],
                'themes': [],
                'sectors': [],
                'event_type': 'news',
                'sentiment': 'neutral',
                'impact_score': 40,
                'urgency': 'low',
                'suggested_action': 'NEWS ONLY',
                'status': 'active',
                'payload': {'verification_status': 'UNVERIFIED', 'catalyst_eligible': False},
            })
            result = clean_old_my_feed_items(apply=True)
            active = list_feed_items(limit=20)
            archived = list_items(limit=20, status='archived')
            all_rows = list_feed_items(limit=20, include_archived=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if int(result.get('archived_count') or 0) < 1:
        return _fail('clean-old must archive at least one dirty row')
    if any('CHAMBLERT' in str(r.get('cleaned_summary') or '').upper() for r in active):
        return _fail('default active list must hide archived CHAMBLERT row')
    if not archived:
        return _fail('archived rows must remain in database')
    if str(archived[0].get('archive_reason') or '') != CLEAN_OLD_ARCHIVE_REASON:
        return _fail(f'archive_reason must be {CLEAN_OLD_ARCHIVE_REASON!r}')
    if len(all_rows) < 2:
        return _fail('list all must still include archived + active rows')

    print('MYFEED_CLEAN_OLD_ARCHIVES_DIRTY_ROWS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
