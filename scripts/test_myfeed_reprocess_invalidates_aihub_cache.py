#!/usr/bin/env python3
"""Stage 50C hotfix 2 — reprocess busts My Feed cache for AIHub full."""

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
BAD = {'FALLS', 'BELOW', 'RS', 'LAKH', 'AMID', 'GLOBAL', 'SELL'}


def _fail(msg: str) -> int:
    print(f'MYFEED_REPROCESS_INVALIDATES_AIHUB_CACHE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.cache_invalidation import (
                get_cached_myfeed_items_for_telegram,
                load_myfeed_items_for_telegram,
            )
            from backend.my_feed.feed_reprocessor import reprocess_my_feed_items
            from backend.my_feed.my_feed_db import insert_feed_item
            from backend.telegram.lazy_command_runner import run_aihub_full_only
            from backend.telegram.response_format import format_aihub_full

            insert_feed_item({
                'source': 'telegram_text',
                'raw_market_text': GOLD_TEXT,
                'cleaned_summary': GOLD_TEXT,
                'tickers': ['GOLD', 'FALLS', 'BELOW', 'RS', 'LAKH', 'AMID', 'GLOBAL', 'SELL'],
                'themes': ['commodity'],
                'event_type': 'commodity',
                'sentiment': 'bearish',
                'impact_score': 70.0,
                'urgency': 'high',
                'suggested_action': 'AVOID',
                'confirmation_required': True,
                'status': 'active',
            })

            stale = load_myfeed_items_for_telegram(limit=5)
            if get_cached_myfeed_items_for_telegram() is None:
                return _fail('first load must populate telegram myfeed cache')

            dirty_full = format_aihub_full(run_aihub_full_only().get('payload') or {})
            if 'FALLS' in dirty_full or 'AVOID' in dirty_full:
                pass
            elif 'GOLD' not in dirty_full:
                return _fail('aihub full must include myfeed section before reprocess')

            result = reprocess_my_feed_items(apply=True, limit=10)
            if result.get('updated', 0) < 1:
                return _fail(f'reprocess must update dirty item, got {result!r}')
            if get_cached_myfeed_items_for_telegram() is not None:
                return _fail('reprocess must invalidate telegram myfeed cache')

            clean_items = load_myfeed_items_for_telegram(limit=5)
            tickers = set((clean_items[0] if clean_items else {}).get('tickers') or [])
            if tickers & BAD:
                return _fail(f'clean cache must drop bad tickers, got {sorted(tickers)}')
            if 'GOLD' not in tickers:
                return _fail('clean cache must keep GOLD entity')

            clean_full = format_aihub_full(run_aihub_full_only().get('payload') or {})
            if any(word in clean_full for word in ('FALLS', 'BELOW', 'RS', 'LAKH', 'AMID', 'GLOBAL', 'SELL')):
                return _fail('aihub full must not show dirty ticker words after reprocess')
            if 'GOLD' not in clean_full:
                return _fail('aihub full must show GOLD after reprocess')
            if 'AVOID' in clean_full:
                return _fail('aihub full must not show AVOID for gold commodity after reprocess')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_REPROCESS_INVALIDATES_AIHUB_CACHE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
