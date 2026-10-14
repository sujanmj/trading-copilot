"""Offline regressions for long-running Railway scheduler ownership."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.utils import process_lock as locks


class ProcessLockTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(directory) / 'master_scheduler.lock'
        self.stack.enter_context(patch.object(locks, 'LOCKS_DIR', Path(directory)))
        self.stack.enter_context(patch.object(locks, 'IS_LOCAL_DEV', False))
        self.stack.enter_context(patch.object(locks, 'ensure_dirs'))
        self.stack.enter_context(patch.object(locks.sys, 'platform', 'linux'))
        self.stack.enter_context(patch.object(locks.time, 'time', return_value=200000.0))
        self.alive = self.stack.enter_context(patch.object(locks, '_pid_alive', return_value=True))
        self.cmdline = self.stack.enter_context(patch.object(
            locks, '_proc_cmdline', return_value='python -m backend.orchestration.master_scheduler'))
        self.info = {'pid': 42, 'script': 'master_scheduler', 'started_at': 1000.0}
        self.path.write_text(json.dumps(self.info))

    def test_verified_live_owner_survives_age_limit_and_blocks_duplicate(self):
        before = self.path.read_bytes()
        self.assertTrue(locks.is_lock_holder_valid('master_scheduler'))
        self.assertFalse(locks.clear_stale_lock('master_scheduler'))
        self.assertFalse(locks.try_acquire_lock('master_scheduler'))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(locks.lock_status()['master_scheduler']['valid'])

    def test_dead_owner_is_still_cleared(self):
        self.alive.return_value = False
        self.assertFalse(locks.is_lock_holder_valid('master_scheduler'))
        self.assertTrue(locks.clear_stale_lock('master_scheduler'))
        self.assertFalse(self.path.exists())

    def test_fresh_scheduler_tick_with_old_live_lock_is_healthy(self):
        from backend.orchestration import orchestrator_state
        state = {'last_scheduler_tick_unix': 199995.0, 'owner_pid': 42}
        with patch.object(orchestrator_state, 'load_orchestrator_state', return_value=state):
            diagnosis = orchestrator_state.validate_singleton_ownership()
        self.assertTrue(diagnosis['healthy'])
        self.assertTrue(diagnosis['lock_valid'])
        self.assertEqual(diagnosis['owner_pid'], 42)
        self.assertEqual(diagnosis['issues'], [])

    def test_reused_pid_with_wrong_process_is_rejected(self):
        self.cmdline.return_value = 'uvicorn backend.api.api_server:app'
        self.assertFalse(locks.is_lock_holder_valid('master_scheduler'))

    def test_linux_owner_without_readable_cmdline_is_not_proven(self):
        self.cmdline.return_value = ''
        self.info['started_at'] = 199999.0
        self.assertFalse(locks.is_lock_holder_valid('master_scheduler', self.info))

    def test_pid_one_cannot_own_scheduler_lock(self):
        self.info['pid'] = 1
        self.assertFalse(locks.is_lock_holder_valid('master_scheduler', self.info))

    def test_pid_only_platform_retains_age_fallback(self):
        with patch.object(locks.sys, 'platform', 'win32'):
            self.assertFalse(locks.is_lock_holder_valid('master_scheduler', self.info))
            self.info['started_at'] = 199999.0
            self.assertTrue(locks.is_lock_holder_valid('master_scheduler', self.info))


if __name__ == '__main__':
    unittest.main()
