#!/usr/bin/env python3
"""Stage 50Y — external trusted-source verification when internal cache misses."""

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
    print(f'MYFEED_EXTERNAL_VERIFICATION_SEARCH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


EXTERNAL_ARTICLE = [{
    'title': 'Adani Ports to invest $850 million in AI and cargo capacity expansion',
    'description': 'APSEZ capex plan for technology and port capacity.',
    'source': 'Moneycontrol Markets',
    'published': '2026-06-17T09:00:00+05:30',
    'link': 'https://www.moneycontrol.com/news/adani-ports-capex',
    'tickers': ['ADANIPORTS'],
}]


def main() -> int:
    from backend.my_feed.feed_processor import ingest_text
    from backend.my_feed.feed_verification import VERIFICATION_VERIFIED

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=[]), \
             patch('backend.my_feed.external_verification_search.search_external_verification_articles', return_value=EXTERNAL_ARTICLE):
            result = ingest_text(
                'Adani Ports to invest $850 million in AI, technology upgrades and cargo capacity expansion',
                source='telegram_text',
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not result.get('ok'):
        return _fail('external verified ingest must save')
    record = result.get('record') or {}
    if str(record.get('verification_status') or '').upper() != VERIFICATION_VERIFIED:
        return _fail(f'expected VERIFIED via external search, got {record!r}')
    if str(record.get('verification_source') or '') != 'external_search':
        return _fail('verification_source must be external_search')
    if 'ADANIPORTS' not in (record.get('tickers') or []):
        return _fail('external verified feed must map to ADANIPORTS')

    print('MYFEED_EXTERNAL_VERIFICATION_SEARCH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
