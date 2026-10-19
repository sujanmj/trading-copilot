#!/usr/bin/env python3
"""Regression tests for scheduled RSS-to-My-Feed persistence."""

from __future__ import annotations

import hashlib
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.my_feed import cache_invalidation, my_feed_db
from backend.my_feed.news_ingestion import ingest_provider_articles
from backend.my_feed.telegram_handlers import format_myfeed_list
from backend.my_feed.feed_processor import sanitize_item_for_api


def _article(**overrides):
    row = {
        'provider_id': 'et_markets',
        'source_name': 'ET Markets',
        'title': 'Indian markets react to RBI policy decision',
        'description': 'Stocks and banking shares respond to the policy announcement.',
        'link': 'https://example.com/markets/rbi-policy?utm_source=rss',
        'published_at': '2026-10-19T08:30:00+00:00',
        'source_time_basis': 'PUBLISHED_PARSED',
        'verification_tier': 3,
        'verification_confidence': 'trusted_media',
        'feed_type': 'macro',
        'tickers': ['NIFTY'],
    }
    row.update(overrides)
    return row


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='astraedge-auto-news-') as tmp:
        db_path = Path(tmp) / 'my_feed.db'
        with (
            patch.object(my_feed_db, 'get_my_feed_db_path', return_value=db_path),
            patch.object(cache_invalidation, 'invalidate_myfeed_caches', return_value={}),
        ):
            article = _article()
            first = ingest_provider_articles([article])
            assert first == {
                'ok': True, 'received': 1, 'inserted': 1,
                'duplicates': 0, 'skipped': 0, 'errors': 0,
                'inserted_items': [{
                    'feed_id': 'rss_' + hashlib.sha256(
                        ('et_markets\nhttps://example.com/markets/rbi-policy\n').encode('utf-8')
                    ).hexdigest()[:28],
                    'title': article['title'],
                    'source_name': 'ET Markets',
                    'source_url': 'https://example.com/markets/rbi-policy',
                    'published_at': article['published_at'],
                    'tickers': ['NIFTY'],
                    'feed_type': 'macro',
                }],
            }, first

            feed_id = 'rss_' + hashlib.sha256(
                ('et_markets\nhttps://example.com/markets/rbi-policy\n').encode('utf-8')
            ).hexdigest()[:28]
            stored = my_feed_db.get_item(feed_id)
            assert stored is not None
            assert stored['source'] == 'auto_news'
            assert stored['source_name'] == 'ET Markets'
            assert stored['source_url'] == 'https://example.com/markets/rbi-policy'
            assert stored['published_at'] == article['published_at']
            assert stored['verification_status'] == 'UNVERIFIED'
            assert stored['catalyst_eligible'] is False
            assert stored['tickers'] == ['NIFTY']
            rendered = format_myfeed_list([sanitize_item_for_api(stored)], title='My Feed (today)')
            assert 'ET Markets · automatically collected' in rendered
            assert 'Indian markets react to RBI policy decision' in rendered

            repeated = ingest_provider_articles([article])
            assert repeated['inserted'] == 0 and repeated['duplicates'] == 1, repeated
            assert len(my_feed_db.list_items(limit=20, status='active')) == 1

            query_article = _article(link='https://example.com/story?id=42&utm_medium=rss')
            query_result = ingest_provider_articles([query_article])
            assert query_result['inserted'] == 1
            query_id = 'rss_' + hashlib.sha256(
                ('et_markets\nhttps://example.com/story?id=42\n').encode('utf-8')
            ).hexdigest()[:28]
            assert my_feed_db.get_item(query_id)['source_url'] == 'https://example.com/story?id=42'

            skipped = ingest_provider_articles([
                _article(provider_id='unknown_site'),
                _article(link='javascript:alert(1)'),
                _article(title=''),
            ])
            assert skipped['inserted'] == 0 and skipped['skipped'] == 3, skipped

    print('PASS: RSS news persists to My Feed with source/time, stable dedupe, and unverified status')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
