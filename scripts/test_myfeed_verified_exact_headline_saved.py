#!/usr/bin/env python3
"""Stage 50W — verified feed stores exact cached headline, not user paraphrase."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXACT_HEADLINE = 'HCL Technologies picks stake in Sarvam AI startup'


def _fail(msg: str) -> int:
    print(f'MYFEED_VERIFIED_EXACT_HEADLINE_SAVED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


MOCK_ARTICLES = [{
    'title': EXACT_HEADLINE,
    'description': 'HCL Tech announced an AI investment in Sarvam AI.',
    'source': 'MoneyControl Markets',
    'published': '2026-06-17T08:15:00+05:30',
    'link': 'https://example.com/hcl-sarvam',
    'tickers': ['HCLTECH'],
}]


def main() -> int:
    from backend.my_feed.feed_processor import ingest_text
    from backend.my_feed.feed_verification import VERIFICATION_VERIFIED

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=MOCK_ARTICLES):
            result = ingest_text('HCL buying stake in Sarvam AI startup', source='telegram_text')
            if not result.get('ok'):
                return _fail('verified ingest failed')
            record = result.get('record') or {}
            if str(record.get('verification_status') or '').upper() != VERIFICATION_VERIFIED:
                return _fail('record must be VERIFIED')
            if str(record.get('verified_headline') or '') != EXACT_HEADLINE:
                return _fail(
                    f'verified_headline must match source exactly, got {record.get("verified_headline")!r}'
                )
            if str(record.get('cleaned_summary') or '') != EXACT_HEADLINE:
                return _fail('cleaned_summary must store verified headline for catalyst use')
            raw = str(record.get('raw_user_text') or record.get('raw_market_text') or '')
            if 'buying stake' not in raw.lower():
                return _fail('raw user text must be preserved separately from verified headline')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_VERIFIED_EXACT_HEADLINE_SAVED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
