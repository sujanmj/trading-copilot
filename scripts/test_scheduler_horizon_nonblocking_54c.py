"""Keep slow outcome price lookups from blocking the scheduler heartbeat."""
from __future__ import annotations

import threading
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.orchestration import master_scheduler


class OutcomeHorizonSchedulerTests(unittest.TestCase):
    def test_slow_evaluation_returns_and_skips_overlapping_run(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow_evaluation():
            started.set()
            release.wait(timeout=3)
            finished.set()
            return {'evaluated': 1}

        with patch(
            'backend.utils.market_hours.get_market_period', return_value='market'
        ), patch(
            'backend.analytics.signal_outcomes.evaluate_due_horizons',
            side_effect=slow_evaluation,
        ) as evaluate:
            try:
                master_scheduler.run_outcome_horizon_tick()
                self.assertTrue(started.wait(timeout=1), 'worker did not start')

                master_scheduler.run_outcome_horizon_tick()
                self.assertEqual(evaluate.call_count, 1)
            finally:
                release.set()

            self.assertTrue(finished.wait(timeout=1), 'worker did not finish')
            self.assertTrue(
                master_scheduler._outcome_horizon_lock.acquire(timeout=1),
                'single-flight guard was not released',
            )
            master_scheduler._outcome_horizon_lock.release()


if __name__ == '__main__':
    unittest.main()
