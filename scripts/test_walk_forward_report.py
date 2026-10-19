#!/usr/bin/env python3
"""Focused checks for the read-only walk-forward research report."""

from __future__ import annotations

import unittest
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.walk_forward_report import _realized_return_pct, _split_dates, _slice_metrics
from backend.analytics import walk_forward_report


class WalkForwardReportTests(unittest.TestCase):
    def test_splits_are_strictly_chronological_and_cover_dates_once(self):
        dates = [f'2026-01-{day:02d}' for day in range(1, 11)]
        splits = _split_dates(dates)
        self.assertLess(max(splits['train']), min(splits['validation']))
        self.assertLess(max(splits['validation']), min(splits['test']))
        self.assertEqual(set.union(*splits.values()), set(dates))
        self.assertEqual(sum(len(rows) for rows in splits.values()), len(dates))

    def test_expired_loss_uses_close_move_not_stop_price(self):
        row = {
            'result': 'LOSS', 'expiry_result': 'EXPIRED', 'direction': 'BULLISH',
            'entry_price': 100, 'stop_loss': 97, 'target_price': 105,
            'close_move_pct': -0.8,
        }
        self.assertEqual(_realized_return_pct(row), -0.8)

    def test_costs_apply_and_ambiguous_candle_is_excluded(self):
        rows = [
            {'result': 'WIN', 'expiry_result': 'TARGET_HIT', 'direction': 'BULLISH',
             'entry_price': 100, 'target_price': 105, 'stop_loss': 97},
            {'result': 'AMBIGUOUS_DAILY_CANDLE'},
        ]
        metrics = _slice_metrics(rows, cost_bps=20)
        self.assertEqual(metrics['signals'], 2)
        self.assertEqual(metrics['scored_trades'], 1)
        self.assertEqual(metrics['ambiguous_excluded'], 1)
        self.assertAlmostEqual(metrics['mean_net_return_pct'], 4.8)

    def test_database_report_splits_one_run_by_signal_date(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.executescript('''
            CREATE TABLE historical_simulation_runs (
                run_id TEXT, market TEXT, from_date TEXT, to_date TEXT,
                strategy_set TEXT, created_at TEXT
            );
            CREATE TABLE historical_simulated_predictions (
                sim_prediction_id TEXT, run_id TEXT, strategy TEXT, ticker TEXT,
                signal_date TEXT, direction TEXT, entry_price REAL,
                target_price REAL, stop_loss REAL
            );
            CREATE TABLE historical_simulated_outcomes (
                sim_prediction_id TEXT, result TEXT, expiry_result TEXT,
                close_move_pct REAL
            );
            INSERT INTO historical_simulation_runs VALUES
                ('run-1', 'INDIA', '2026-01-01', '2026-01-10', 'test', 'now');
        ''')
        for index in range(10):
            day = f'2026-01-{index + 1:02d}'
            conn.execute(
                'INSERT INTO historical_simulated_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (f'p{index}', 'run-1', 'breakout', 'TEST', day, 'BULLISH', 100, 105, 97),
            )
            conn.execute(
                'INSERT INTO historical_simulated_outcomes VALUES (?, ?, ?, ?)',
                (f'p{index}', 'WIN' if index % 2 == 0 else 'LOSS', 'EXPIRED',
                 1.0 if index % 2 == 0 else -1.0),
            )
        conn.commit()
        try:
            with patch.object(walk_forward_report, 'get_connection', return_value=conn), \
                 patch.object(walk_forward_report, 'list_runs', return_value=[{'run_id': 'run-1'}]):
                report = walk_forward_report.get_walk_forward_report(market='INDIA', cost_bps=10)
            strategy = report['strategies'][0]
            self.assertEqual(strategy['splits']['train']['scored_trades'], 6)
            self.assertEqual(strategy['splits']['validation']['scored_trades'], 2)
            self.assertEqual(strategy['splits']['test']['scored_trades'], 2)
            self.assertLess(strategy['splits']['train']['to_date'], strategy['splits']['validation']['from_date'])
            self.assertLess(strategy['splits']['validation']['to_date'], strategy['splits']['test']['from_date'])
            self.assertEqual(strategy['splits']['test']['cost_bps_round_trip'], 10)
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
