"""Offline regressions for safe scheduler ownership recovery."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.orchestration.scheduler_supervision import wait_for_child


class FakeProcess:
    def __init__(self, *, kill_required=False):
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.wait_calls = 0
        self.kill_required = kill_required

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.returncode is not None:
            return self.returncode
        if timeout is None:
            raise AssertionError('scheduler wait must be interruptible')
        if self.wait_calls == 1:
            raise subprocess.TimeoutExpired('scheduler', timeout)
        if self.terminated and not self.kill_required:
            self.returncode = -15
            return self.returncode
        if self.killed:
            self.returncode = -9
            return self.returncode
        raise subprocess.TimeoutExpired('scheduler', timeout)

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class SchedulerSupervisionTests(unittest.TestCase):
    def test_stale_live_owner_lock_is_not_force_deleted(self):
        # The repository's market-time dependency is not needed by this path.
        sys.modules.setdefault('pytz', SimpleNamespace(timezone=ZoneInfo))
        from backend.orchestration import recovery_loop
        with patch.object(recovery_loop, 'validate_singleton_ownership', return_value={
            'tick_age_seconds': 400,
        }), patch('backend.utils.process_lock.clear_stale_lock', return_value=False) as clear, \
             patch('backend.utils.process_lock.force_clear_lock') as force_clear:
            self.assertFalse(recovery_loop.safe_clear_stale_locks('test_stale'))
        clear.assert_called_once_with('master_scheduler')
        force_clear.assert_not_called()

    def test_recovery_signal_stops_unhealthy_child_for_supervised_relaunch(self):
        process = FakeProcess()
        result = wait_for_child(
            process,
            scheduler=True,
            recovery_requested=lambda: True,
            scheduler_healthy=lambda: False,
            poll_seconds=1,
            terminate_timeout=1,
            startup_grace_seconds=0,
        )
        self.assertEqual(result, -15)
        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)

    def test_healthy_scheduler_ignores_recovery_signal(self):
        process = FakeProcess()
        process.wait = lambda timeout=None: setattr(process, 'returncode', 0) or 0
        result = wait_for_child(
            process,
            scheduler=True,
            recovery_requested=lambda: True,
            scheduler_healthy=lambda: True,
            poll_seconds=1,
            startup_grace_seconds=0,
        )
        self.assertEqual(result, 0)
        self.assertFalse(process.terminated)

    def test_stuck_child_is_killed_after_terminate_timeout(self):
        process = FakeProcess(kill_required=True)
        result = wait_for_child(
            process,
            scheduler=True,
            recovery_requested=lambda: True,
            scheduler_healthy=lambda: False,
            poll_seconds=1,
            terminate_timeout=1,
            startup_grace_seconds=0,
        )
        self.assertEqual(result, -9)
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)

    def test_startup_grace_does_not_consume_retry_signal(self):
        process = FakeProcess()
        def startup_wait(timeout=None):
            process.wait_calls += 1
            if process.wait_calls == 1:
                raise subprocess.TimeoutExpired('scheduler', timeout)
            process.returncode = 0
            return 0

        process.wait = startup_wait
        retry_checks = []
        with patch('backend.orchestration.scheduler_supervision.time.monotonic', side_effect=(0, 5)):
            result = wait_for_child(
                process,
                scheduler=True,
                recovery_requested=lambda: retry_checks.append(True) or True,
                scheduler_healthy=lambda: False,
                poll_seconds=1,
                startup_grace_seconds=10,
            )
        self.assertEqual(result, 0)
        self.assertEqual(retry_checks, [])
        self.assertFalse(process.terminated)


if __name__ == '__main__':
    unittest.main()
