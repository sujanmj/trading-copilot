#!/usr/bin/env python3
"""Unit tests for weekend premarket scheduler suppression (Stage 47C/47D)."""

from __future__ import annotations

import os
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WEEKEND_ALERT_SLOTS = (
    'premarket_top3',
    'premarket_action',
    'preopen_watch',
    'live_validation',
    'open_confirmation',
)


def _fail(msg: str) -> int:
    print(f'WEEKEND_SCHEDULER_QUIET_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram import premarket_scheduler as sched

    if sched.WEEKEND_SUPPRESS_SEND_SLOTS != frozenset(WEEKEND_ALERT_SLOTS):
        return _fail(f'unexpected suppress slots: {sched.WEEKEND_SUPPRESS_SEND_SLOTS}')

    with patch.object(sched, '_is_weekend_research_mode', return_value=True):
        with patch(
            'backend.analytics.premarket_conviction.send_scheduled_premarket',
            return_value=True,
        ) as send_mock:
            buf = StringIO()
            with patch('sys.stdout', buf):
                for slot in WEEKEND_ALERT_SLOTS:
                    ok = sched.run_premarket_slot(slot)
                    if ok:
                        return _fail(f'{slot} should not send on weekend')
            out = buf.getvalue()
            if send_mock.called:
                return _fail('send_scheduled_premarket must not run on weekend scheduled slots')
            if '[PREMARKET_SCHED] sent slot=' in out:
                return _fail('sent log must not appear during weekend scheduled run')
            for slot in WEEKEND_ALERT_SLOTS:
                marker = (
                    f'WEEKEND_SCHEDULE_SUPPRESSED premarket_alert reason=weekend_research_mode '
                    f'slot={slot}'
                )
                if marker not in out:
                    return _fail(f'missing suppression log for {slot}')

    with patch.object(sched, '_is_weekend_research_mode', return_value=False):
        with patch(
            'backend.analytics.premarket_conviction.send_scheduled_premarket',
            return_value=True,
        ) as send_mock:
            with patch('sys.stdout', StringIO()):
                sched.run_premarket_slot('premarket_top3')
            if not send_mock.called:
                return _fail('weekday premarket_top3 should send')

    from backend.analytics.premarket_conviction import format_premarket_telegram

    with patch('backend.analytics.premarket_conviction._is_weekend_holiday_research', return_value=True):
        text = format_premarket_telegram(full=False, report={'weekend_research_mode': True, 'top_setups': []})
        if 'WEEKEND RESEARCH' not in text:
            return _fail('manual /premarket should still work on weekend')

    print('WEEKEND_SCHEDULER_QUIET_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
