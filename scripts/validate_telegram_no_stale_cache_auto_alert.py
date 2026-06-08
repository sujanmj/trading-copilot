#!/usr/bin/env python3
"""Validate scheduler never auto-sends stale-cache macro research (Stage 48G)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_NO_STALE_CACHE_AUTO_ALERT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    engine_src = (PROJECT_ROOT / 'backend/orchestration/telegram_alert_engine.py').read_text(encoding='utf-8')
    if 'TELEGRAM_MACRO_STALE_SUPPRESSED' not in engine_src:
        return _fail('missing TELEGRAM_MACRO_STALE_SUPPRESSED guard')

    sched_src = (PROJECT_ROOT / 'backend/orchestration/alert_scheduler.py').read_text(encoding='utf-8')
    if 'try_emergency_macro()' not in sched_src:
        return _fail('alert_scheduler must call try_emergency_macro()')

    if os.system(f'{sys.executable} scripts/test_telegram_no_stale_cache_auto_alert.py') != 0:
        return _fail('test_telegram_no_stale_cache_auto_alert.py failed')

    print('TELEGRAM_NO_STALE_CACHE_AUTO_ALERT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
