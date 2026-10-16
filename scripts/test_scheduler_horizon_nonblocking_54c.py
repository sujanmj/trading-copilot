"""Keep slow outcome price lookups from blocking the scheduler heartbeat."""
from __future__ import annotations

import threading
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.orchestration import master_scheduler
from backend.orchestration import schedule_registry


class OutcomeHorizonSchedulerTests(unittest.TestCase):
    def test_deferred_ist_job_stays_running_until_worker_finishes(self):
        original_jobs = list(schedule_registry._IST_JOBS)
        original_fired = dict(schedule_registry._ist_last_fired)
        original_status = dict(schedule_registry._job_runtime_status)
        try:
            schedule_registry._IST_JOBS[:] = [{
                'name': 'deferred_test',
                'hour': 9,
                'minute': 30,
                'weekdays_only': True,
                'fn': lambda: schedule_registry.DEFERRED_JOB,
            }]
            schedule_registry._ist_last_fired.clear()
            schedule_registry._job_runtime_status.clear()
            with patch('backend.orchestration.schedule_registry.datetime') as clock:
                clock.now.return_value = schedule_registry.IST.localize(
                    datetime(2026, 10, 16, 9, 30)
                )
                self.assertEqual(schedule_registry.tick_ist_jobs(), ['deferred_test'])
            self.assertEqual(
                schedule_registry._job_runtime_status['deferred_test'], 'running'
            )
        finally:
            schedule_registry._IST_JOBS[:] = original_jobs
            schedule_registry._ist_last_fired.clear()
            schedule_registry._ist_last_fired.update(original_fired)
            schedule_registry._job_runtime_status.clear()
            schedule_registry._job_runtime_status.update(original_status)

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

    def test_slow_full_cycle_runs_off_loop_and_skips_overlap(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        worker_threads = []

        def slow_cycle(**kwargs):
            worker_threads.append(threading.current_thread())
            started.set()
            release.wait(timeout=1)
            finished.set()

        with patch('backend.orchestration.master_scheduler.run_full_cycle', side_effect=slow_cycle) as cycle:
            try:
                self.assertIs(
                    master_scheduler.run_full_cycle_async('test', job_name='test_cycle'),
                    master_scheduler.DEFERRED_JOB,
                )
                self.assertTrue(started.wait(timeout=1), 'full-cycle worker did not start')
                self.assertIsNot(worker_threads[0], threading.current_thread())
                self.assertIs(
                    master_scheduler.run_full_cycle_async('duplicate', job_name='duplicate_cycle'),
                    master_scheduler.DEFERRED_JOB,
                )
                self.assertEqual(cycle.call_count, 1)
            finally:
                release.set()

            self.assertTrue(finished.wait(timeout=1), 'full-cycle worker did not finish')
            self.assertTrue(
                master_scheduler._full_cycle_lock.acquire(timeout=1),
                'single-flight guard was not released',
            )
            master_scheduler._full_cycle_lock.release()


if __name__ == '__main__':
    unittest.main()
