#!/usr/bin/env python3
"""Validate Stage 50L daily review pending alert tracking."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'DAILY_REVIEW_TRACKS_PENDING_ALERTS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/analytics/eod_outcome_scoring.py').read_text(encoding='utf-8')
    for needle in (
        'summarize_alert_review_tracking',
        'format_daily_review_alert_lines',
        'pending_review_count',
        'intraday_alert_count',
    ):
        if needle not in src:
            return _fail(f'eod_outcome_scoring missing {needle}')
    proc = os.system(f'{sys.executable} scripts/test_daily_review_tracks_pending_alerts.py')
    if proc != 0:
        return _fail('test_daily_review_tracks_pending_alerts.py failed')
    print('DAILY_REVIEW_TRACKS_PENDING_ALERTS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
