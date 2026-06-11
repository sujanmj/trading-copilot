#!/usr/bin/env python3
"""Stage 50H — /myfeed clean-old archives dirty image/OCR rows, keeps clean text."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

GOLD_TEXT = 'Gold falls below Rs 1.5 lakh amid global sell-off on safe-haven demand'


def _fail(msg: str) -> int:
    print(f'MYFEED_CLEAN_OLD_DIRTY_ROWS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.clean_old import clean_old_my_feed_items, format_clean_old_reply, is_dirty_feed_item
            from backend.my_feed.my_feed_db import insert_feed_item, list_items

            assert is_dirty_feed_item({
                'source': 'telegram_screenshot',
                'tickers': ['RELIANCE'],
                'cleaned_summary': 'test',
                'status': 'active',
            })[0] is True

            assert is_dirty_feed_item({
                'source': 'telegram_text',
                'tickers': ['GOLD'],
                'suggested_action': 'GOLD WATCH',
                'cleaned_summary': GOLD_TEXT,
                'status': 'active',
            })[0] is False

            insert_feed_item({
                'source': 'gui_screenshot',
                'raw_market_text': 'CHAMBLERT results today',
                'cleaned_summary': 'CHAMBLERT results today',
                'tickers': ['CHAMBLERT', 'INDIA'],
                'themes': [],
                'event_type': 'news',
                'sentiment': 'neutral',
                'impact_score': 40.0,
                'urgency': 'normal',
                'suggested_action': 'NEWS ONLY',
                'confirmation_required': True,
                'status': 'active',
            })
            insert_feed_item({
                'source': 'telegram_text',
                'raw_market_text': GOLD_TEXT,
                'cleaned_summary': GOLD_TEXT,
                'tickers': ['GOLD'],
                'themes': ['commodity'],
                'event_type': 'commodity',
                'sentiment': 'bearish',
                'impact_score': 70.0,
                'urgency': 'high',
                'suggested_action': 'GOLD WATCH',
                'confirmation_required': True,
                'status': 'active',
            })

            preview = clean_old_my_feed_items(apply=False, limit=10)
            if int(preview.get('archived_count') or 0) < 1:
                return _fail(f'preview must detect dirty row: {preview!r}')

            result = clean_old_my_feed_items(apply=True, limit=10)
            reply = format_clean_old_reply(result)
            if 'MYFEED_CLEAN_OLD_OK' not in reply:
                return _fail(f'missing clean-old reply token: {reply!r}')
            if int(result.get('archived_count') or 0) < 1:
                return _fail(f'apply must archive dirty row: {result!r}')

            active = list_items(limit=10, status='active')
            if len(active) != 1:
                return _fail(f'expected one active clean row, got {len(active)}')
            if str(active[0].get('suggested_action') or '') != 'GOLD WATCH':
                return _fail('clean GOLD WATCH row must remain active')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_CLEAN_OLD_DIRTY_ROWS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
