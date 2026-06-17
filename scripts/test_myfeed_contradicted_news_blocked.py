#!/usr/bin/env python3
"""Stage 50W — contradicted My Feed claims are blocked from catalyst use."""

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
    print(f'MYFEED_CONTRADICTED_NEWS_BLOCKED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


MOCK_ARTICLES = [{
    'title': 'RELIANCE shares fall 5% after weak earnings miss',
    'description': 'Reliance Industries reported weaker than expected quarterly earnings.',
    'source': 'Mint Markets',
    'published': '2026-06-17T09:30:00+05:30',
    'link': 'https://example.com/reliance-fall',
    'tickers': ['RELIANCE'],
}]


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import _iter_my_feed_text
    from backend.my_feed.feed_processor import ingest_text
    from backend.my_feed.feed_verification import VERIFICATION_CONTRADICTED

    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / 'my_feed.db'
    try:
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=MOCK_ARTICLES):
            result = ingest_text(
                'RELIANCE shares surge 5% on strong earnings beat',
                source='telegram_text',
            )
            if not result.get('ok'):
                return _fail('contradicted ingest must still save for audit')
            reply = str(result.get('reply') or '')
            if VERIFICATION_CONTRADICTED not in reply:
                return _fail(f'reply must show CONTRADICTED, got {reply!r}')
            if '❌ Feed claim contradicted' not in reply:
                return _fail('reply must include contradicted warning')
            record = result.get('record') or {}
            if str(record.get('verification_status') or '').upper() != VERIFICATION_CONTRADICTED:
                return _fail('stored verification_status must be CONTRADICTED')
            if _iter_my_feed_text():
                return _fail('contradicted feed must not enter catalyst iterator')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_CONTRADICTED_NEWS_BLOCKED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
