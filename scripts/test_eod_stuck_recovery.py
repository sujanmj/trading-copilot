#!/usr/bin/env python3
"""Regression checks for stale EOD progress detection and safe replay gating."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytz
from backend.orchestration import eod_recovery, recovery_loop

IST = pytz.timezone('Asia/Kolkata')


class StuckEodRecoveryTests(unittest.TestCase):
    def test_running_heartbeat_is_fresh_until_threshold(self):
        now = IST.localize(datetime(2026, 10, 21, 20, 0))
        state = {
            'pipeline_status': 'RUNNING',
            'heartbeat_at': (now - timedelta(seconds=eod_recovery.EOD_STALE_RUNNING_SECONDS - 1)).isoformat(),
            'current_stage': 'daily_review',
        }
        self.assertFalse(eod_recovery.get_stale_running_details(state, now)['stale'])

    def test_old_running_heartbeat_reports_stage_and_age(self):
        now = IST.localize(datetime(2026, 10, 21, 20, 0))
        state = {
            'pipeline_status': 'RUNNING',
            'heartbeat_at': (now - timedelta(seconds=eod_recovery.EOD_STALE_RUNNING_SECONDS + 30)).isoformat(),
            'current_stage': 'tomorrow_intelligence',
        }
        details = eod_recovery.get_stale_running_details(state, now)
        self.assertTrue(details['stale'])
        self.assertEqual(details['stage'], 'tomorrow_intelligence')
        self.assertGreater(details['age_seconds'], eod_recovery.EOD_STALE_RUNNING_SECONDS)

    def test_stale_running_cycle_only_replays_after_owner_lock_is_gone(self):
        now = IST.localize(datetime(2026, 10, 21, 20, 0))
        state = {
            'pipeline_status': 'RUNNING',
            'heartbeat_at': (now - timedelta(seconds=eod_recovery.EOD_STALE_RUNNING_SECONDS + 1)).isoformat(),
            'current_stage': 'daily_review',
        }
        with patch.object(eod_recovery, '_today', return_value='2026-10-21'), \
             patch('backend.lifecycle.prediction_lifecycle_engine.load_lifecycle_state', return_value=state), \
             patch('backend.utils.process_lock.lock_status', return_value={
                 'eod_lifecycle': {'valid': True, 'alive': True},
             }):
            should, reason = eod_recovery.needs_eod_recovery(now)
        self.assertFalse(should)
        self.assertTrue(reason.startswith('stale_pipeline_owner_alive:'))

        with patch.object(eod_recovery, '_today', return_value='2026-10-21'), \
             patch('backend.lifecycle.prediction_lifecycle_engine.load_lifecycle_state', return_value=state), \
             patch('backend.utils.process_lock.lock_status', return_value={
                 'eod_lifecycle': {'valid': False, 'alive': False},
             }):
            should, reason = eod_recovery.needs_eod_recovery(now)
        self.assertTrue(should)
        self.assertTrue(reason.startswith('stale_pipeline_recovery:'))

    def test_stale_or_failed_lifecycle_blocks_scheduler_health(self):
        owner = {'healthy': True, 'lock_valid': True, 'tick_age_seconds': 3, 'issues': []}
        old_state = {
            'pipeline_status': 'RUNNING',
            'heartbeat_at': '2026-10-21T15:00:00+05:30',
            'current_stage': 'tomorrow_intelligence',
        }
        with patch.object(recovery_loop, '_quiet_period', return_value=True), \
             patch.object(recovery_loop, 'validate_singleton_ownership', return_value=owner), \
             patch.object(recovery_loop, 'load_orchestrator_state', return_value={}), \
             patch.object(recovery_loop, 'detect_duplicate_workers', return_value=[]), \
             patch('backend.lifecycle.lifecycle_tracing.load_lifecycle_state', return_value=old_state):
            diagnosis = recovery_loop.diagnose_runtime()
        self.assertFalse(diagnosis['healthy'])
        self.assertTrue(any(issue.startswith('lifecycle_stuck:tomorrow_intelligence:') for issue in diagnosis['issues']))

        with patch.object(recovery_loop, '_quiet_period', return_value=True), \
             patch.object(recovery_loop, 'validate_singleton_ownership', return_value=owner), \
             patch.object(recovery_loop, 'load_orchestrator_state', return_value={}), \
             patch.object(recovery_loop, 'detect_duplicate_workers', return_value=[]), \
             patch('backend.lifecycle.lifecycle_tracing.load_lifecycle_state', return_value={'pipeline_status': 'FAILED'}):
            diagnosis = recovery_loop.diagnose_runtime()
        self.assertFalse(diagnosis['healthy'])
        self.assertIn('lifecycle_failed', diagnosis['issues'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
