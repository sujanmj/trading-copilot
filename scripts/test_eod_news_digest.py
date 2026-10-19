#!/usr/bin/env python3
"""Regression tests for the scheduled EOD news gap digest."""

from __future__ import annotations

import sys
from types import ModuleType
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend.my_feed.news_ingestion as news_ingestion
from backend.my_feed.eod_news_digest import format_eod_news_digest, run_eod_news_digest

IST = ZoneInfo('Asia/Kolkata')


class EodNewsDigestTests(unittest.TestCase):
    def test_daily_scheduler_registers_digest_for_all_days(self):
        from backend.orchestration import master_scheduler, schedule_registry

        job = next(
            task for task in schedule_registry.get_task_registry()['tasks']
            if task.get('name') == 'eod_news_digest'
        )
        self.assertEqual((job['schedule'], job['weekdays_only']), ('22:00 IST', False))

    def test_only_new_stories_published_today_are_sent_with_source_links(self):
        refresh = {
            'ok': True,
            'sources_checked': 11,
            'output': {'articles': [{'title': 'new'}, {'title': 'old'}]},
            'provider_status': {'et_markets': {'freshness_status': 'CURRENT'}},
        }
        inserted = {
            'ok': True,
            'received': 2,
            'inserted': 2,
            'inserted_items': [
                {
                    'title': 'RBI changes policy stance', 'source_name': 'ET Markets',
                    'source_url': 'https://example.com/rbi',
                    'published_at': '2026-10-19T12:00:00+00:00', 'tickers': ['NIFTY'],
                },
                {
                    'title': 'Yesterday close recap', 'source_name': 'Mint',
                    'source_url': 'https://example.com/old',
                    'published_at': '2026-10-18T17:00:00+00:00', 'tickers': [],
                },
            ],
        }
        sent = []

        def send_fn(message, **kwargs):
            sent.append((message, kwargs))
            return {'ok': True, 'sent': True}

        fake_registry = ModuleType('backend.collectors.news_provider_registry')
        fake_registry.run_unified_news_refresh = unittest.mock.Mock(return_value=refresh)
        with patch.dict(sys.modules, {'backend.collectors.news_provider_registry': fake_registry}), patch.object(
            news_ingestion, 'ingest_provider_articles', return_value=inserted
        ) as ingest_mock:
            result = run_eod_news_digest(
                now=datetime(2026, 10, 19, 22, 0, tzinfo=IST), send_fn=send_fn
            )

        fake_registry.run_unified_news_refresh.assert_called_once_with(
            hours_back=36, send_macro_alerts=False
        )
        ingest_mock.assert_called_once_with(refresh['output']['articles'])
        self.assertEqual(result['new_stories_today'], 1)
        self.assertIn('RBI changes policy stance', sent[0][0])
        self.assertIn('https://example.com/rbi', sent[0][0])
        self.assertNotIn('Yesterday close recap', sent[0][0])
        self.assertIn('UNVERIFIED', sent[0][0])
        self.assertEqual(sent[0][1], {'command': 'eod_news_digest', 'parse_mode': ''})

    def test_empty_and_unavailable_source_messages_are_truthful(self):
        empty = format_eod_news_digest(
            day=datetime(2026, 10, 19).date(), sources_checked=11,
            inserted_count=0, stories=[], failed_sources=[],
        )
        self.assertIn('No new, timestamped stories', empty)
        unavailable = format_eod_news_digest(
            day=datetime(2026, 10, 19).date(), sources_checked=2,
            inserted_count=0, stories=[], failed_sources=['et_markets', 'mint_rss'],
        )
        self.assertIn('could not reach any enabled source', unavailable)


if __name__ == '__main__':
    unittest.main(verbosity=2)
