#!/usr/bin/env python3
"""Validate premarket hard stale lock (Stage 47D)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'PREMARKET_HARD_STALE_LOCK_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    gate_src = (PROJECT_ROOT / 'backend/orchestration/alert_freshness_gate.py').read_text(encoding='utf-8')
    for needle in (
        'PREMARKET_INCOMPLETE_HEADER',
        'premarket_hard_stale_lock',
        'apply_hard_stale_lock_to_setups',
        'NO LIVE SETUPS',
    ):
        if needle not in gate_src:
            return _fail(f'alert_freshness_gate missing {needle}')

    lazy_src = (PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py').read_text(encoding='utf-8')
    if 'dry_run: bool = False' not in lazy_src:
        return _fail('_scoped_refresh missing dry_run parameter')

    if os.system(f'{sys.executable} scripts/test_premarket_hard_stale_lock.py') != 0:
        return _fail('test_premarket_hard_stale_lock.py failed')

    print('PREMARKET_HARD_STALE_LOCK_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
