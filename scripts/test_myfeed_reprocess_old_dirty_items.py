#!/usr/bin/env python3
"""Stage 50C hotfix — reprocess cleans dirty tickers on old My Feed items."""

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
    print(f'MYFEED_REPROCESS_OLD_DIRTY_ITEMS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.feed_reprocessor import format_reprocess_reply, reprocess_my_feed_items
            from backend.my_feed.my_feed_db import get_item, insert_feed_item

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

            preview = reprocess_my_feed_items(apply=False, limit=10)
            if preview.get('updated', 0) < 1:
                return _fail(f'dry-run must detect dirty item, got {preview!r}')

            result = reprocess_my_feed_items(apply=True, limit=10)
            reply = format_reprocess_reply(result)
            if 'MYFEED_REPROCESS_OK' not in reply:
                return _fail(f'missing reprocess reply token: {reply!r}')
            if result.get('updated', 0) < 1:
                return _fail(f'apply must update dirty item, got {result!r}')

            items = __import__('backend.my_feed.my_feed_db', fromlist=['list_items']).list_items(limit=5, status=None)
            item = items[0] if items else {}
            tickers = set(item.get('tickers') or [])
            if tickers & BAD:
                return _fail(f'bad tickers remain after reprocess: {sorted(tickers & BAD)}')
            if 'GOLD' not in tickers:
                return _fail(f'expected GOLD ticker, got {sorted(tickers)}')
            action = str(item.get('suggested_action') or '')
            if action == 'AVOID':
                return _fail('gold commodity item must not remain AVOID after reprocess')
            if action not in {'GOLD WATCH', 'COMMODITY RISK ALERT'}:
                return _fail(f'expected GOLD WATCH or COMMODITY RISK ALERT, got {action!r}')
            if str(item.get('cleaned_summary') or '') != GOLD_TEXT:
                return _fail('reprocess must preserve cleaned_summary text')
            if str(item.get('raw_market_text') or '') != GOLD_TEXT:
                return _fail('reprocess must preserve raw_market_text')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_REPROCESS_OLD_DIRTY_ITEMS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
