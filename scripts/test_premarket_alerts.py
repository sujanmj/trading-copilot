#!/usr/bin/env python3
"""Unit tests for premarket alerts (Stage 46G)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

FORBIDDEN = ('buy now', 'invest now', 'guaranteed')
REQUIRED = ('watch for entry', 'confirm after 9:15', 'no blind entry')


def _fail(msg: str) -> int:
    print(f'PREMARKET_ALERTS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.premarket_conviction import (
        build_premarket_conviction_report,
        format_premarket_telegram,
    )
    from backend.telegram.premarket_scheduler import PREMARKET_SLOTS, SCHEDULE_DISPLAY
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command

    report = build_premarket_conviction_report(persist=True)
    if report.get('top_setups') is None:
        return _fail('report missing top_setups')
    if report.get('stage') != '46G':
        return _fail('report stage not 46G')

    text = format_premarket_telegram(full=False, report=report)
    lower = text.lower()
    for phrase in REQUIRED:
        if phrase not in lower:
            return _fail(f'missing required phrase: {phrase}')
    for bad in FORBIDDEN:
        if bad in lower:
            return _fail(f'forbidden phrase in message: {bad}')

    full = format_premarket_telegram(full=True, report=report)
    if 'PREMARKET FULL' not in full:
        return _fail('full premarket format missing FULL marker')

    expected_times = {(7, 45), (8, 0), (8, 15), (8, 30), (8, 45), (9, 10), (9, 20), (9, 30)}
    slot_times = set(PREMARKET_SLOTS.values())
    if not expected_times.issubset(slot_times):
        return _fail(f'scheduler missing slots: {expected_times - slot_times}')
    if len(SCHEDULE_DISPLAY) < 8:
        return _fail('schedule display incomplete')

    if '/premarket' not in HELP_TEXT:
        return _fail('/premarket missing from help')
    if '/premarket full' not in HELP_TEXT.lower() and 'premarket full' not in HELP_TEXT.lower():
        return _fail('/premarket full missing from help')

    results = handle_analysis_command('/premarket', 'test', dry_run=True)
    if not results or 'PREMARKET' not in str(results[0].get('text', '')).upper():
        return _fail('/premarket command failed')
    results_full = handle_analysis_command('/premarket full', 'test', dry_run=True)
    if not results_full:
        return _fail('/premarket full command failed')

    print('PREMARKET_ALERTS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
