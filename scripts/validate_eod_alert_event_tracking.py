#!/usr/bin/env python3
"""Validate EOD alert event tracking pack (Stage 46I)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'EOD_ALERT_EVENT_TRACKING_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    log_path = PROJECT_ROOT / 'backend/orchestration/alert_event_log.py'
    if not log_path.is_file():
        return _fail('missing alert_event_log.py')

    eod_src = (PROJECT_ROOT / 'backend/analytics/eod_outcome_scoring.py').read_text(encoding='utf-8')
    if 'alert_event_log' not in eod_src:
        return _fail('eod_outcome_scoring missing alert_event_log')

    proc = os.system(f'{sys.executable} scripts/test_eod_alert_event_tracking.py')
    if proc != 0:
        return _fail('test_eod_alert_event_tracking.py failed')

    print('EOD_ALERT_EVENT_TRACKING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
