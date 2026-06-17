#!/usr/bin/env python3
"""Stage 50X — Adani unverified feed visible in list but not catalyst-eligible."""

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
    print(f'MYFEED_ADANI_UNVERIFIED_VISIBLE_NOT_USED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import _iter_my_feed_text
    from backend.my_feed.feed_processor import ingest_text, list_feed_items
    from backend.my_feed.feed_verification import VERIFICATION_UNVERIFIED, is_catalyst_eligible_item
    from backend.my_feed.telegram_handlers import format_myfeed_list

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=[]):
            result = ingest_text('adani lost airport contract to kenya', source='telegram_text')
            items = list_feed_items(limit=5, verification_filter='unverified')
            list_text = format_myfeed_list(items, title='My Feed (unverified)')
            catalyst_rows = list(_iter_my_feed_text())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    record = result.get('record') or {}
    if str(record.get('verification_status') or '').upper() != VERIFICATION_UNVERIFIED:
        return _fail('adani claim without cache must stay UNVERIFIED')
    if is_catalyst_eligible_item(record):
        return _fail('unverified adani row must not be catalyst eligible')
    if not items:
        return _fail('unverified list filter must show adani row')
    if 'adani' not in list_text.lower():
        return _fail('list output must show adani claim text')
    if any('adani' in str(row.get('cleaned_summary') or '').lower() for row in catalyst_rows):
        return _fail('catalyst iterator must not boost unverified adani feed')
    if 'BUY' in list_text.upper() or 'SELL' in list_text.upper():
        return _fail('list must not contain BUY/SELL wording')

    print('MYFEED_ADANI_UNVERIFIED_VISIBLE_NOT_USED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
