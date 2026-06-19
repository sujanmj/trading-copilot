#!/usr/bin/env python3
"""Stage 50Y — verified reply includes headline, source, catalyst evidence."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

HEADLINE = 'Adani Ports to invest $850 million in AI and cargo capacity expansion'


def _fail(msg: str) -> int:
    print(f'MYFEED_VERIFIED_REPLY_SOURCE_HEADLINE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


MOCK = [{
    'title': HEADLINE,
    'description': 'APSEZ investment plan.',
    'source': 'Moneycontrol Markets',
    'published': '2026-06-17T09:00:00+05:30',
    'link': 'https://example.com/adani-ports',
    'tickers': ['ADANIPORTS'],
}]


def main() -> int:
    from backend.my_feed.feed_processor import ingest_text

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=MOCK):
            result = ingest_text(
                'Adani Ports to invest $850 million in AI and cargo capacity expansion',
                source='telegram_text',
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    reply = str(result.get('reply') or '')
    if '✅ Feed verified' not in reply:
        return _fail('reply must show verified banner')
    if f'Headline: {HEADLINE}' not in reply:
        return _fail('reply must include exact verified headline')
    if 'Source: Moneycontrol Markets' not in reply:
        return _fail('reply must include trusted source name')
    if 'Used as catalyst evidence: yes' not in reply:
        return _fail('reply must confirm catalyst evidence yes')
    if 'BUY' in reply.upper() or 'SELL' in reply.upper():
        return _fail('reply must not contain BUY/SELL wording')

    print('MYFEED_VERIFIED_REPLY_SOURCE_HEADLINE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
