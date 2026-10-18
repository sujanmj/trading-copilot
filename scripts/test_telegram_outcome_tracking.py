#!/usr/bin/env python3
"""Regression tests for persisted Telegram win/loss scoring and notices."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IST = ZoneInfo('Asia/Kolkata')


class TelegramOutcomeTrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / 'trading_history.db'
        self.market_path = self.root / 'latest_market_data.json'
        from backend.storage import db_manager
        from backend.analytics import signal_outcomes
        from backend.utils import telegram_bot

        self.db_manager = db_manager
        self.signal_outcomes = signal_outcomes
        self.telegram_bot = telegram_bot
        self.db_path_patch = patch.object(db_manager, 'DB_PATH', self.db_path)
        self.market_path_patch = patch.object(signal_outcomes, 'MARKET_DATA_FILE', self.market_path)
        self.db_path_patch.start()
        self.market_path_patch.start()
        db_manager._init_db_logged = False
        db_manager.init_db()

    def tearDown(self):
        self.market_path_patch.stop()
        self.db_path_patch.stop()
        self.temp.cleanup()

    def _create_event(self, event_ts: datetime, *, ticker='TST', entry=100.0, direction='BUY', version='v2'):
        event_id = self.signal_outcomes._insert_event({
            'event_ts': event_ts.isoformat(),
            'event_date': event_ts.date().isoformat(),
            'signal_type': 'telegram',
            'source': 'INTRADAY_OPPORTUNITY',
            'ticker': ticker,
            'direction': direction,
            'confidence': 0.7,
            'confidence_band': 'MEDIUM',
            'regime': 'sideways',
            'entry_price': entry,
            'dedupe_key': f'test_{ticker}_{event_ts.isoformat()}',
            'metadata': {'test': True},
        })
        if version != 'v2':
            conn = self.db_manager.get_connection()
            conn.execute('UPDATE signal_events SET tracking_version=? WHERE id=?', (version, event_id))
            conn.commit()
            conn.close()
        return event_id

    def _write_price(self, ticker: str, price: float, observed_at: datetime, *, timestamped=True):
        observation = {'ltp': price, 'source': 'test_feed'}
        if timestamped:
            observation['validated_at'] = observed_at.isoformat()
        self.market_path.write_text(json.dumps({'prices': {ticker: observation}}), encoding='utf-8')

    def test_final_horizon_persists_win_and_sends_one_notice(self):
        event_ts = datetime(2026, 10, 12, 10, 0, tzinfo=IST)
        event_id = self._create_event(event_ts)
        due = event_ts + timedelta(days=1)
        due = due.replace(hour=15, minute=35, second=0, microsecond=0)
        observed = due + timedelta(minutes=5)
        self._write_price('TST', 102.0, observed)
        telegram_result = {'sent': True, 'reason': ''}
        with patch.object(self.telegram_bot, 'send_message_result', return_value=telegram_result) as send:
            result = self.signal_outcomes.evaluate_due_horizons(now=observed + timedelta(minutes=1))
            self.assertEqual(result['evaluated'], 1)
            self.assertEqual(result['notifications_sent'], 1)
            result = self.signal_outcomes.evaluate_due_horizons(now=observed + timedelta(minutes=2))
            self.assertEqual(result['evaluated'], 0)
            self.assertEqual(result['notifications_sent'], 0)
            self.assertEqual(send.call_count, 1)
            self.assertIn('WON', send.call_args.args[0])

        conn = self.db_manager.get_connection()
        try:
            row = conn.execute(
                "SELECT hit_miss, resolution_status, price, change_pct, observed_at, price_source "
                "FROM signal_horizons WHERE event_id=? AND horizon='next_day'", (event_id,)
            ).fetchone()
            notification = conn.execute(
                "SELECT status, attempts FROM signal_outcome_notifications WHERE event_id=? AND horizon='next_day'",
                (event_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row['hit_miss'], 'HIT')
        self.assertEqual(row['resolution_status'], 'RESOLVED')
        self.assertEqual(row['price'], 102.0)
        self.assertEqual(row['change_pct'], 2.0)
        self.assertEqual(row['price_source'], 'test_feed')
        self.assertEqual(notification['status'], 'SENT')
        self.assertEqual(notification['attempts'], 1)

    def test_late_or_untimestamped_price_is_unresolved_not_a_loss(self):
        event_ts = datetime(2026, 10, 12, 10, 0, tzinfo=IST)
        event_id = self._create_event(event_ts)
        due = (event_ts + timedelta(days=1)).replace(hour=15, minute=35, second=0, microsecond=0)
        too_late = due + timedelta(hours=2)
        self._write_price('TST', 80.0, too_late)
        result = self.signal_outcomes.evaluate_due_horizons(now=too_late + timedelta(minutes=1))
        self.assertEqual(result['evaluated'], 0)
        self.assertEqual(result['unresolved'], 4)
        conn = self.db_manager.get_connection()
        try:
            row = conn.execute(
                "SELECT hit_miss, resolution_status, resolution_reason, price "
                "FROM signal_horizons WHERE event_id=? AND horizon='next_day'", (event_id,)
            ).fetchone()
            notices = conn.execute(
                'SELECT count(*) FROM signal_outcome_notifications WHERE event_id=?', (event_id,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(row['hit_miss'], 'PENDING')
        self.assertEqual(row['resolution_status'], 'UNRESOLVED')
        self.assertEqual(row['resolution_reason'], 'no_timestamped_price_in_horizon_window')
        self.assertIsNone(row['price'])
        self.assertEqual(notices, 0)

    def test_legacy_rows_are_not_rewritten_by_new_evaluator(self):
        event_ts = datetime(2026, 10, 12, 10, 0, tzinfo=IST)
        event_id = self._create_event(event_ts, version=None)
        due = (event_ts + timedelta(days=1)).replace(hour=15, minute=35, second=0, microsecond=0)
        now = due + timedelta(days=3)
        self._write_price('TST', 110.0, now)
        self.signal_outcomes.evaluate_due_horizons(now=now)
        conn = self.db_manager.get_connection()
        try:
            row = conn.execute(
                "SELECT hit_miss, resolution_status FROM signal_horizons "
                "WHERE event_id=? AND horizon='next_day'", (event_id,)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row['hit_miss'], 'PENDING')
        self.assertEqual(row['resolution_status'], 'PENDING')

    def test_missing_timestamp_never_scores_current_price(self):
        event_ts = datetime(2026, 10, 12, 10, 0, tzinfo=IST)
        event_id = self._create_event(event_ts)
        due = (event_ts + timedelta(days=1)).replace(hour=15, minute=35, second=0, microsecond=0)
        now = due + timedelta(minutes=5)
        self._write_price('TST', 120.0, now, timestamped=False)
        self.signal_outcomes.evaluate_due_horizons(now=now)
        conn = self.db_manager.get_connection()
        try:
            row = conn.execute(
                "SELECT hit_miss, resolution_status FROM signal_horizons "
                "WHERE event_id=? AND horizon='next_day'", (event_id,)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row['hit_miss'], 'PENDING')
        self.assertEqual(row['resolution_status'], 'PENDING')

    def test_eod_counts_only_final_horizon_and_maps_hit_miss_to_win_loss(self):
        from backend.analytics.eod_outcome_scoring import _query_telegram_alert_outcomes

        event_ts = datetime(2026, 10, 18, 10, 0, tzinfo=IST)
        winner = self._create_event(event_ts, ticker='WINNER')
        loser = self._create_event(event_ts + timedelta(minutes=1), ticker='LOSER', direction='SELL')
        conn = self.db_manager.get_connection()
        try:
            conn.execute(
                "UPDATE signal_horizons SET hit_miss='HIT', resolution_status='RESOLVED', change_pct=2 "
                "WHERE event_id=? AND horizon='next_day'", (winner,)
            )
            conn.execute(
                "UPDATE signal_horizons SET hit_miss='MISS', resolution_status='RESOLVED', change_pct=-2 "
                "WHERE event_id=? AND horizon='next_day'", (loser,)
            )
            conn.commit()
        finally:
            conn.close()

        summary = _query_telegram_alert_outcomes('2026-10-18')
        counts = summary['by_type']['open_setup']
        self.assertEqual(counts['WIN'], 1)
        self.assertEqual(counts['LOSS'], 1)
        self.assertEqual(counts['PENDING'], 0)
        self.assertEqual(len(summary['rows']), 2)

    def test_separate_same_day_alerts_get_separate_outcome_records(self):
        base = datetime(2026, 10, 18, 10, 0, tzinfo=IST)
        first = self.signal_outcomes.track_telegram_alert(
            category='INTRADAY_OPPORTUNITY', ticker='TST', direction='BUY',
            entry_price=100, event_ts=base.isoformat(), entry_source='scanner_data',
        )
        second = self.signal_outcomes.track_telegram_alert(
            category='INTRADAY_OPPORTUNITY', ticker='TST', direction='BUY',
            entry_price=101, event_ts=(base + timedelta(minutes=10)).isoformat(), entry_source='scanner_data',
        )
        self.assertNotEqual(first, second)
        conn = self.db_manager.get_connection()
        try:
            count = conn.execute(
                "SELECT count(*) FROM signal_events WHERE signal_type='telegram' AND ticker='TST'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
