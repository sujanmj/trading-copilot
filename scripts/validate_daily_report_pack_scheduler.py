#!/usr/bin/env python3
"""
Validate daily report pack scheduler registration and dry-run.

Prints exactly DAILY_REPORT_PACK_SCHEDULER_OK on success.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

REQUIRED_JOBS = (
    'premarket_report_pack',
    'postmarket_report_pack',
    'research_mode_report_pack',
)


def _fail(msg: str) -> int:
    print(f'DAILY_REPORT_PACK_SCHEDULER_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def _apply_local_defaults() -> None:
    for key, val in {
        'LOCAL_DEV_MODE': '1',
        'LOCAL_ONLY': '1',
        'DISABLE_TELEGRAM': '1',
        'DISABLE_TELEGRAM_LISTENER': '1',
        'DISABLE_TELEGRAM_SENDS': '1',
    }.items():
        os.environ.setdefault(key, val)


def main() -> int:
    _apply_local_defaults()

    job_module = PROJECT_ROOT / 'backend' / 'scheduler' / 'daily_report_pack_job.py'
    if not job_module.is_file():
        return _fail('missing daily_report_pack_job.py')

    import backend.orchestration.master_scheduler  # noqa: F401

    from backend.orchestration.schedule_registry import get_task_registry

    names = {str(t.get('name') or '').lower() for t in (get_task_registry().get('tasks') or [])}
    missing = [job for job in REQUIRED_JOBS if job not in names]
    if missing:
        return _fail(f'scheduler missing jobs: {", ".join(missing)}')

    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / 'daily_startup_check.py'), '--skip-api'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    combined = (proc.stdout or '') + (proc.stderr or '')
    if 'report_pack_scheduler=ok' not in combined:
        return _fail('daily_startup_check report_pack_scheduler not ok')
    if 'DAILY_STARTUP_READY' not in combined and 'DAILY_STARTUP_READY_WITH_WARNINGS' not in combined:
        return _fail('daily_startup_check not ready')

    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / 'run_daily_report_pack_job.py'), '--mode', 'auto', '--dry-run'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0 or 'DAILY_REPORT_PACK_JOB_OK' not in (proc.stdout or ''):
        tail = (proc.stderr or proc.stdout or '').strip().splitlines()
        return _fail(tail[-1] if tail else 'dry-run job failed')

    print('DAILY_REPORT_PACK_SCHEDULER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
