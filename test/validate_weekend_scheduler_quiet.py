#!/usr/bin/env python3
"""Validate weekend premarket scheduler suppression (Stage 47C)."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'WEEKEND_SCHEDULER_QUIET_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram import premarket_scheduler as sched

    suppress = sched.WEEKEND_SUPPRESS_SEND_SLOTS
    expected = {'premarket_top3', 'preopen_watch', 'live_validation', 'open_confirmation'}
    if suppress != expected:
        return _fail(f'unexpected suppress slots: {suppress}')

    weekend = datetime(2026, 6, 6, 8, 30, tzinfo=ZoneInfo('Asia/Kolkata'))

    with patch.object(sched, '_is_weekend_research_mode', return_value=True):
        buf = StringIO()
        with patch('sys.stdout', buf):
            ok = sched.run_premarket_slot('premarket_top3')
        out = buf.getvalue()
        if ok:
            return _fail('premarket_top3 should not send on weekend')
        if 'WEEKEND_SCHEDULE_SUPPRESSED premarket_alert reason=weekend_research_mode' not in out:
            return _fail('missing WEEKEND_SCHEDULE_SUPPRESSED log line')

    with patch.object(sched, '_is_weekend_research_mode', return_value=True):
        with patch('backend.analytics.premarket_conviction.send_scheduled_premarket', return_value=True) as send_mock:
            sched.run_premarket_slot('premarket_action')
            if not send_mock.called:
                return _fail('premarket_action (08:45) should still send on weekend')

    with patch.object(sched, '_is_weekend_research_mode', return_value=False):
        with patch('backend.analytics.premarket_conviction.send_scheduled_premarket', return_value=True) as send_mock:
            sched.run_premarket_slot('premarket_top3')
            if not send_mock.called:
                return _fail('weekday premarket_top3 should send')

    from backend.analytics.premarket_conviction import format_premarket_telegram

    with patch('backend.analytics.premarket_conviction._is_weekend_holiday_research', return_value=True):
        text = format_premarket_telegram(full=False, report={'weekend_research_mode': True, 'top_setups': []})
        if 'WEEKEND RESEARCH' not in text:
            return _fail('manual /premarket should still work on weekend')

    print('WEEKEND_SCHEDULER_QUIET_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
