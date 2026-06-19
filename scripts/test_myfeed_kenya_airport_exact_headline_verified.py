#!/usr/bin/env python3
"""Stage 50Y — Kenya airport stores exact verified headline wording."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXACT = (
    'China Wins $2.9 Billion Kenya Airport Deal, About 50% Higher Than Shelved Adani Proposal'
)


def _fail(msg: str) -> int:
    print(f'MYFEED_KENYA_AIRPORT_EXACT_HEADLINE_VERIFIED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


EXTERNAL = [{
    'title': EXACT,
    'description': 'China Communications Construction wins Kenya airport contract over shelved Adani proposal.',
    'source': 'NDTV Profit',
    'published': '2026-06-17T11:00:00+05:30',
    'link': 'https://www.ndtvprofit.com/kenya-airport-china-adani',
    'tickers': ['ADANIENT'],
}]


def main() -> int:
    from backend.my_feed.feed_processor import ingest_text
    from backend.my_feed.feed_verification import VERIFICATION_VERIFIED

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=[]), \
             patch('backend.my_feed.external_verification_search.search_external_verification_articles', return_value=EXTERNAL):
            result = ingest_text(
                'China wins $2.9 billion Kenya airport deal, about 50% higher than shelved Adani proposal',
                source='telegram_text',
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    record = result.get('record') or {}
    if str(record.get('verification_status') or '').upper() != VERIFICATION_VERIFIED:
        return _fail(f'expected VERIFIED, got {record!r}')
    if str(record.get('verified_headline') or '') != EXACT:
        return _fail(f'must store exact headline, got {record.get("verified_headline")!r}')
    if 'lost contract today' in str(record.get('verified_headline') or '').lower():
        return _fail('must not invent lost contract wording')
    raw = str(record.get('raw_user_text') or record.get('raw_market_text') or '').lower()
    if 'shelved adani proposal' not in raw:
        return _fail('raw user text must be preserved separately')

    print('MYFEED_KENYA_AIRPORT_EXACT_HEADLINE_VERIFIED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
