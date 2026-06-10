#!/usr/bin/env python3
"""Unit tests — Stage 48T /full polish + regression hooks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

FORBIDDEN = ('Stale: no', 'cache age: old cache')


def _fail(msg: str) -> int:
    print(f'FULL_SNAPSHOT_POLISH_48T_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _run(script: str, token: str) -> int | None:
    proc = subprocess.run([sys.executable, f'scripts/{script}'], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    combined = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0 or token not in combined:
        return _fail(f'{script} failed: {combined.strip()[-200:]}')
    return None


def main() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
    from backend.telegram.lazy_command_runner import FULL_SNAPSHOT_EXCLUDED, FULL_SNAPSHOT_SEQUENCE
    from backend.telegram.response_format import format_status_text, strip_stage_markers

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 50B':
        return _fail(f'expected AstraEdge 50B got {ASTRAEDGE_TELEGRAM_BUILD!r}')

    status = strip_stage_markers(format_status_text())
    if 'Telegram build: <code>AstraEdge 50B</code>' not in status:
        return _fail('/status missing AstraEdge 50B build label')
    for needle in FORBIDDEN:
        if needle in status:
            return _fail(f'/status contains forbidden stale wording: {needle!r}')

    if len(FULL_SNAPSHOT_SEQUENCE) != 32:
        return _fail(f'/full sequence must have 32 steps, got {len(FULL_SNAPSHOT_SEQUENCE)}')
    for cmd in FULL_SNAPSHOT_SEQUENCE:
        if cmd.lstrip('/') in {'refresh', 'bootstrap'} or cmd in FULL_SNAPSHOT_EXCLUDED:
            return _fail(f'/full must stay read-only; found {cmd!r}')

    for script, token in (
        ('test_remove_stale_no_old_cache_wording.py', 'REMOVE_STALE_NO_OLD_CACHE_WORDING_TEST_OK'),
        ('test_after_hours_scanner_wording.py', 'AFTER_HOURS_SCANNER_WORDING_TEST_OK'),
        ('test_aihub_rejected_watchlist_clarity.py', 'AIHUB_REJECTED_WATCHLIST_CLARITY_TEST_OK'),
        ('test_aihub_calib_outcomes_unresolved_live.py', 'AIHUB_CALIB_OUTCOMES_UNRESOLVED_LIVE_TEST_OK'),
        ('test_live_rejection_hard_override.py', 'LIVE_REJECTION_HARD_OVERRIDE_TEST_OK'),
    ):
        err = _run(script, token)
        if err:
            return err

    print('FULL_SNAPSHOT_POLISH_48T_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
