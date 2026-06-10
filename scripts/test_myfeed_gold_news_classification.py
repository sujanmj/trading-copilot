#!/usr/bin/env python3
"""Unit tests — gold commodity news classification (Stage 50C)."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

GOLD_NEWS = 'Gold falls below Rs 1.5 lakh amid global sell-off on stronger dollar'
ALLOWED_ACTIONS = frozenset({'GOLD WATCH', 'COMMODITY RISK ALERT'})


def _fail(msg: str) -> int:
    print(f'MYFEED_GOLD_NEWS_CLASSIFICATION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.feed_processor import _classify_item, ingest_text

    extracted = {
        'cleaned_summary': GOLD_NEWS,
        'items_found': 1,
        'tickers': ['GOLD'],
    }
    classified = _classify_item(extracted)
    action = str(classified.get('suggested_action') or '')
    if action not in ALLOWED_ACTIONS:
        return _fail(f'gold news action must be GOLD WATCH or COMMODITY RISK ALERT, got {action!r}')
    if action == 'AVOID':
        return _fail('gold commodity fall must not classify as AVOID')

    themes = classified.get('themes') or []
    if 'Precious Metals' not in themes:
        return _fail(f'gold news must include Precious Metals theme, got {themes!r}')
    if 'Commodity Risk' not in themes:
        return _fail(f'gold news must include Commodity Risk theme, got {themes!r}')

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            result = ingest_text(GOLD_NEWS, source='telegram_text')
            if not result.get('ok'):
                return _fail('gold news ingest failed')
            record = result.get('record') or {}
            stored_action = str(record.get('suggested_action') or '')
            if stored_action not in ALLOWED_ACTIONS:
                return _fail(f'stored gold action must be GOLD WATCH or COMMODITY RISK ALERT, got {stored_action!r}')
            stored_themes = record.get('themes') or []
            if 'Precious Metals' not in stored_themes or 'Commodity Risk' not in stored_themes:
                return _fail(f'stored gold themes wrong: {stored_themes!r}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_GOLD_NEWS_CLASSIFICATION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
