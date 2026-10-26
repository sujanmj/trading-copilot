#!/usr/bin/env python3
"""Public health/build metadata exposes safe EOD recovery evidence."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class EodHealthObservabilityTests(unittest.TestCase):
    def test_orchestrator_health_carries_eod_progress_and_last_success(self):
        from backend.orchestration import orchestrator_state

        lifecycle = {
            'pipeline_status': 'RUNNING',
            'exports_fresh': False,
            'last_eod_cycle_date': '2026-10-19',
            'last_eod_cycle_at': '2026-10-19T15:51:48+05:30',
            'last_successful_eod': '2026-10-19T15:51:48+05:30',
            'heartbeat_at': '2026-10-19T15:52:00+05:30',
            'current_stage': 'daily_review',
            'recovery_reason': 'test-recovery',
            'stats_age_minutes': 5,
            'history_age_minutes': 5,
            'brain_age_minutes': 5,
        }
        with patch.object(orchestrator_state, 'load_orchestrator_state', return_value={}), \
             patch.object(orchestrator_state, 'validate_singleton_ownership', return_value={
                 'healthy': True, 'lock_valid': True, 'tick_age_seconds': 1,
                 'lock_age_seconds': 1, 'owner_pid': 1, 'issues': [],
             }), \
             patch('backend.lifecycle.prediction_lifecycle_engine.get_lifecycle_status', return_value=lifecycle), \
             patch.object(orchestrator_state, 'save_orchestrator_state', side_effect=lambda value: value):
            payload = orchestrator_state.refresh_component_snapshot()

        observed = payload['components']['lifecycle']
        for key in ('last_eod_cycle_date', 'last_eod_cycle_at', 'last_successful_eod',
                    'heartbeat_at', 'current_stage', 'recovery_reason'):
            self.assertEqual(observed[key], lifecycle[key])

    def test_build_info_exposes_deployed_commit_sha(self):
        from backend.api.api_server import api_debug_build_info

        with patch.dict(os.environ, {'RAILWAY_GIT_COMMIT_SHA': 'a' * 40}):
            payload = api_debug_build_info()
        self.assertEqual(payload['commit_sha'], 'a' * 40)


if __name__ == '__main__':
    unittest.main(verbosity=2)
