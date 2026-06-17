#!/usr/bin/env python3
"""Stage 50W — verified My Feed items integrate into catalyst radar."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXACT_HEADLINE = 'Wipro wins large digital transformation deal from US client'


def _fail(msg: str) -> int:
    print(f'MYFEED_VERIFIED_CATALYST_INTEGRATION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


MOCK_ARTICLES = [{
    'title': EXACT_HEADLINE,
    'description': 'Wipro secured a multi-year digital transformation contract.',
    'source': 'NDTV Profit',
    'published': '2026-06-17T11:00:00+05:30',
    'link': 'https://example.com/wipro-deal',
    'tickers': ['WIPRO'],
}]


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import _collect_raw_catalysts, build_catalyst_radar
    from backend.my_feed.feed_processor import ingest_text

    tmp = tempfile.mkdtemp()
    cache_file = Path(tmp) / 'stock_catalyst_radar_latest.json'
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=MOCK_ARTICLES):
            ingest_result = ingest_text('Wipro wins big digital deal from US client', source='telegram_text')
            if not ingest_result.get('ok'):
                return _fail('verified feed ingest failed')

        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.intelligence.stock_catalyst_radar._load_json', return_value={}), \
             patch('backend.intelligence.stock_catalyst_radar._iter_external_evidence', return_value=[]), \
             patch('backend.intelligence.stock_catalyst_radar._iter_inshorts', return_value=[]), \
             patch('backend.intelligence.stock_catalyst_radar._iter_nse_filings', return_value=[]), \
             patch('backend.intelligence.stock_catalyst_radar.CACHE_FILE', cache_file):
            raw = _collect_raw_catalysts()
            radar = build_catalyst_radar(persist=False, force_refresh=True)

        wipro_rows = [r for r in raw if str(r.get('ticker') or '').upper() == 'WIPRO']
        if not wipro_rows:
            return _fail('verified My Feed must contribute WIPRO catalyst row')
        headline = str(wipro_rows[0].get('headline') or '')
        if EXACT_HEADLINE not in headline and headline != EXACT_HEADLINE:
            return _fail(f'catalyst headline must use verified source headline, got {headline!r}')
        if not any(str(r.get('source_key') or '') == 'my_feed' for r in raw):
            return _fail('catalyst raw rows must include my_feed source_key')
        if not radar.get('items'):
            return _fail('catalyst radar items must not be empty with verified feed')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_VERIFIED_CATALYST_INTEGRATION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
