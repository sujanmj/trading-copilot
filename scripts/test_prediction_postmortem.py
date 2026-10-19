#!/usr/bin/env python3
"""Focused checks for persistent EOD postmortems and historical event analogs."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics import prediction_postmortem as postmortem
from backend.analytics import eod_outcome_scoring
from backend.ai import ask_context_builder
from backend.storage import prediction_postmortem_store as store


class PredictionPostmortemTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / 'memory.db'

        def connect():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            return conn

        self.patches = [
            patch.object(store, 'init_market_memory_db', return_value=True),
            patch.object(store, 'get_connection', side_effect=connect),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def test_eod_queue_persists_source_link_and_completes_idempotently(self):
        loss = {
            'snapshot_id': 'snap-loss-1', 'symbol': 'ADANIPOWER',
            'session_date': '2026-10-19', 'snapshot_at': '2026-10-19T09:30:00+05:30',
            'stage': 'final_0931', 'outcome': 'LOSS', 'close_return_pct': -1.2,
            'max_favorable_excursion_pct': 0.4, 'max_adverse_excursion_pct': -1.5,
            'news_headline': 'Adani Power tender update', 'resolved_at': '2026-10-19T15:45:00+05:30',
            'reason_tags': ['no_volume_followthrough'],
        }
        source = {
            'source_name': 'Business Standard', 'title': 'Adani Power update',
            'url': 'https://example.test/adani-power',
            'published_at': '2026-10-19T10:00:00+00:00', 'snippet': 'A relevant company update.',
        }
        with patch.object(postmortem, 'search_prediction_day_news', return_value=[source]), \
             patch.object(postmortem, '_explain_loss', return_value={
                 'success': True, 'cause_category': 'NEWS_AND_MOMENTUM',
                 'cause_summary': 'The news may have affected sentiment.',
                 'confidence': 0.7, 'provider': 'test', 'model': 'test-model',
             }):
            result = postmortem.process_candidate_postmortems([loss], session_date='2026-10-19')

        self.assertEqual(result['saved'], 1)
        self.assertEqual(result['completed'], 1)
        rows = store.get_postmortems(symbol='ADANIPOWER', limit=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['evidence_status'], 'COMPLETE')
        self.assertEqual(rows[0]['cause_category'], 'NEWS_AND_MOMENTUM')
        self.assertEqual(rows[0]['evidence'][0]['url'], source['url'])
        listing = postmortem.format_postmortems_telegram(symbol='ADANIPOWER')
        digest = postmortem.format_eod_postmortem_digest('2026-10-19')
        self.assertIn('ADANIPOWER', listing)
        self.assertIn(source['url'], listing)
        self.assertIn('EOD prediction postmortems', digest)
        self.assertIn('Adani Power update', digest)
        with patch.object(eod_outcome_scoring, 'summarize_alert_review_tracking', return_value={}), \
             patch.object(eod_outcome_scoring, 'format_daily_review_alert_lines', return_value=['Alerts tracked: 0']):
            eod_message = eod_outcome_scoring.format_eod_telegram_message({
                'date': '2026-10-19', 'resolved': 1, 'data_available': True,
                'wins': 0, 'losses': 1, 'neutrals': 0, 'partials': 0,
                'best': [], 'worst': [],
            })
        self.assertIn(source['url'], eod_message)

        with patch.object(postmortem, 'search_prediction_day_news') as search, \
             patch.object(postmortem, '_explain_loss') as explain:
            postmortem.process_candidate_postmortems([loss], session_date='2026-10-19')
        search.assert_not_called()
        explain.assert_not_called()
        self.assertEqual(len(store.get_postmortems(symbol='ADANIPOWER', limit=5)), 1)

    def test_event_analogs_are_descriptive_and_require_minimum_sample(self):
        for index in range(5):
            store.upsert_postmortem({
                'snapshot_id': f'win-{index}', 'symbol': f'TEST{index}',
                'session_date': '2026-10-19', 'outcome': 'WIN',
                'close_return_pct': 1.0, 'event_type': 'RESULTS_NEWS',
                'event_text': 'quarterly result announcement', 'context': {},
            })
        for index in range(2):
            store.upsert_postmortem({
                'snapshot_id': f'loss-{index}', 'symbol': f'FAIL{index}',
                'session_date': '2026-10-19', 'outcome': 'LOSS',
                'close_return_pct': -1.0, 'event_type': 'RESULTS_NEWS',
                'event_text': 'quarterly result announcement', 'context': {},
            })
        with patch.object(postmortem, '_event_type', return_value='RESULTS_NEWS'):
            result = postmortem.get_candidate_event_analogs(
                {'ticker': 'NEWCO', 'news_headline': 'quarterly results'}, min_samples=5,
            )
        self.assertTrue(result['available'])
        self.assertEqual(result['sample_count'], 7)
        self.assertEqual(result['wins'], 5)
        self.assertEqual(result['losses'], 2)
        self.assertTrue(result['research_only'])
        first_page = postmortem.format_postmortems_telegram(page=1, page_size=5)
        second_page = postmortem.format_postmortems_telegram(page=2, page_size=5)
        self.assertIn('Next: /postmortems 2', first_page)
        self.assertIn('Previous: /postmortems 1', second_page)

    def test_eod_searches_and_reports_every_final_0931_loss_without_ai_budget(self):
        losses = []
        for index in range(7):
            losses.append({
                'snapshot_id': f'loss-0931-{index}', 'symbol': f'LOSER{index}',
                'session_date': '2026-10-19', 'snapshot_at': '2026-10-19T09:31:00+05:30',
                'stage': 'final_0931', 'outcome': 'LOSS', 'close_return_pct': -0.8,
                'max_favorable_excursion_pct': 0.1, 'max_adverse_excursion_pct': -1.1,
                'resolved_at': '2026-10-19T15:45:00+05:30',
            })
        # A same-day loss from an earlier candidate stage must not appear in
        # the report that is specifically about the 09:31 list.
        losses.append({
            'snapshot_id': 'loss-opening', 'symbol': 'OPENING',
            'session_date': '2026-10-19', 'snapshot_at': '2026-10-19T09:20:00+05:30',
            'stage': 'opening_0920', 'outcome': 'LOSS', 'close_return_pct': -1.2,
            'resolved_at': '2026-10-19T15:45:00+05:30',
        })
        def source_for(*, symbol, **_kwargs):
            return [{
                'source_name': 'Test News', 'title': f'{symbol} news',
                'url': f'https://example.test/{symbol}',
                'published_at': '2026-10-19T10:00:00+00:00', 'snippet': 'News evidence.',
            }]
        with patch.object(postmortem, 'search_prediction_day_news', side_effect=source_for) as search, \
             patch.object(postmortem, '_explain_loss') as explain:
            result = postmortem.process_candidate_postmortems(
                losses, session_date='2026-10-19', ai_limit=0,
            )
        self.assertEqual(result['searched'], 7, result)
        self.assertEqual(search.call_count, 7)
        explain.assert_not_called()
        digest = postmortem.format_eod_postmortem_digest('2026-10-19')
        for index in range(7):
            self.assertIn(f'LOSER{index}', digest)
            self.assertIn(f'https://example.test/LOSER{index}', digest)
        self.assertNotIn('OPENING', digest)
        self.assertIn('AI explanation queued', digest)

    def test_ask_ai_context_includes_saved_source_linked_postmortems(self):
        row = {
            'symbol': 'ADANIPOWER', 'session_date': '2026-10-19', 'outcome': 'LOSS',
            'close_return_pct': -1.2, 'event_type': 'RESULTS_NEWS',
            'evidence_status': 'COMPLETE', 'cause_summary': 'Possible sentiment shift.',
            'event_text': 'quarterly result update',
            'evidence': [{'published_at': '2026-10-19T10:00:00Z',
                          'title': 'Company update', 'url': 'https://example.test/source'}],
        }
        with patch.object(postmortem, 'get_postmortem_context_for_question', return_value=[row]):
            context = ask_context_builder._postmortem_section('Why did ADANI POWER fail?')
        self.assertIn('ADANIPOWER 2026-10-19 LOSS', context)
        self.assertIn('Possible sentiment shift.', context)
        self.assertIn('https://example.test/source', context)


if __name__ == '__main__':
    unittest.main()
