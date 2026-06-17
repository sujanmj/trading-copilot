#!/usr/bin/env python3
"""Stage 50W — verified My Feed news intake pipeline."""

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
    print(f'MYFEED_VERIFIED_NEWS_INTAKE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


MOCK_ARTICLES = [{
    'title': 'TCS wins large AI cloud contract from global bank',
    'description': 'Tata Consultancy Services secured a multi-year AI cloud contract.',
    'source': 'Economic Times',
    'published': '2026-06-17T10:00:00+05:30',
    'link': 'https://example.com/tcs-ai-cloud',
    'tickers': ['TCS'],
}]


def main() -> int:
    from backend.my_feed.feed_processor import ingest_text
    from backend.my_feed.feed_verification import VERIFICATION_VERIFIED

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=MOCK_ARTICLES):
            result = ingest_text('TCS wins large AI cloud contract from global bank', source='telegram_text')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not result.get('ok'):
        return _fail('verified ingest must succeed')
    reply = str(result.get('reply') or '')
    if 'MY_FEED_SAVED' not in reply:
        return _fail('reply must include MY_FEED_SAVED')
    if VERIFICATION_VERIFIED not in reply:
        return _fail(f'reply must show VERIFIED status, got {reply!r}')
    if '✅ Feed verified' not in reply:
        return _fail('reply must include verified confirmation line')
    record = result.get('record') or {}
    if str(record.get('verification_status') or '').upper() != VERIFICATION_VERIFIED:
        return _fail(f'record verification_status must be VERIFIED, got {record!r}')

    print('MYFEED_VERIFIED_NEWS_INTAKE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
