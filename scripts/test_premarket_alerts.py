#!/usr/bin/env python3
"""Unit tests for premarket alerts (Stage 46H)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

FORBIDDEN = ('buy now', 'invest now', 'guaranteed')
REQUIRED_ALWAYS = ('no blind entry', 'watch for entry')


def _fail(msg: str) -> int:
    print(f'PREMARKET_ALERTS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.premarket_conviction import (
        _apply_conflict_guard,
        _apply_volume_caps,
        _format_sentiment_value,
        build_premarket_conviction_report,
        format_premarket_telegram,
    )
    from backend.telegram.premarket_scheduler import PREMARKET_SLOTS, SCHEDULE_DISPLAY
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command

    report = build_premarket_conviction_report(persist=True)
    if report.get('top_setups') is None:
        return _fail('report missing top_setups')
    if not report.get('stage'):
        return _fail('report missing stage')

    from backend.analytics.market_calendar_router import is_weekend_holiday_research_telegram_mode
    from backend.analytics.premarket_conviction import _is_after_open

    weekend = is_weekend_holiday_research_telegram_mode(report.get('market_mode') or {})
    text = format_premarket_telegram(full=False, report=report)
    lower = text.lower()
    if not weekend:
        if 'no blind entry' not in lower:
            return _fail('missing required phrase: no blind entry')
        if _is_after_open():
            if 'wait for volume' not in lower and 'watch for entry' not in lower:
                return _fail('after open: missing wait for volume or watch for entry')
        elif 'watch for entry' not in lower:
            return _fail('missing required phrase: watch for entry')
    else:
        for phrase in REQUIRED_ALWAYS:
            if phrase not in lower:
                return _fail(f'weekend missing required phrase: {phrase}')
    if not _is_after_open():
        if weekend:
            if 'confirm on next trading session after 9:15' not in lower:
                return _fail('weekend missing next-session confirm wording')
        elif 'confirm after 9:15' not in lower:
            return _fail('missing confirm after 9:15 before market open')
    for bad in FORBIDDEN:
        if bad in lower:
            return _fail(f'forbidden phrase in message: {bad}')

    full = format_premarket_telegram(full=True, report=report)
    if weekend:
        if 'WEEKEND RESEARCH BRIEF' not in full:
            return _fail('weekend full premarket missing research brief title')
    else:
        mode = str((report.get('market_mode') or {}).get('market_mode') or '')
        live_hours = 'INDIA_MARKET_HOURS' in mode and _is_after_open()
        if live_hours:
            if 'LIVE MARKET BRIEF' not in full:
                return _fail('market-hours full premarket missing LIVE MARKET BRIEF title')
        elif not any(
            marker in full
            for marker in ('PREMARKET FULL', 'LIVE MARKET BRIEF', 'AFTER-HOURS FULL BRIEF')
        ):
            return _fail('full premarket format missing FULL or LIVE marker')
    if '{' in full and '}' in full and "'summary'" in full:
        return _fail('premarket full must not contain raw dict')
    if not weekend and 'US/global context only' not in full:
        return _fail('full premarket missing US/global context-only label')

    sent = _format_sentiment_value({'summary': 'Neutral', 'bias': 'Cautious'})
    if '{' in sent:
        return _fail('sentiment formatter leaked dict')

    capped, deferred_low = _apply_volume_caps(
        [{'ticker': 'ABC', 'score': 80, 'setup': 'WATCH', 'reasons': []}],
        {'top_signals': [{'ticker': 'ABC', 'volume_ratio': 0.25}]},
        {},
    )
    if not deferred_low and (not capped or capped[0].get('tier_cap') != 'not_top3'):
        return _fail('vol<0.3 should cap top3 or defer')
    _capped2, deferred = _apply_volume_caps(
        [{'ticker': 'ABC', 'score': 80, 'setup': 'WATCH', 'reasons': []}],
        {'top_signals': [{'ticker': 'ABC', 'volume_ratio': 0.25}]},
        {},
    )
    if not deferred:
        return _fail('vol<0.3 should defer from top watch')

    conflicted = _apply_conflict_guard(
        [{'ticker': 'XYZ', 'score': 70, 'setup': 'WATCH'}],
        [{'ticker': 'XYZ', 'reason': 'weak'}],
    )
    if conflicted[0].get('setup') != 'Conflict/Wait':
        return _fail('top watch + avoid should be Conflict/Wait')

    expected_times = {(7, 45), (8, 0), (8, 15), (8, 30), (8, 45)}
    slot_times = set(PREMARKET_SLOTS.values())
    if not expected_times.issubset(slot_times):
        return _fail(f'scheduler missing build slots: {expected_times - slot_times}')
    if (9, 10) in slot_times:
        return _fail('09:10 pre-open alert must not exist')
    from backend.telegram.premarket_scheduler import OPENING_MORNING_SLOTS, OPENING_SCHEDULE_LABELS

    opening_times = set(OPENING_MORNING_SLOTS.values())
    if opening_times != {(9, 0), (9, 20), (9, 25), (9, 31)}:
        return _fail(f'unexpected opening morning slots: {opening_times}')
    if len(OPENING_SCHEDULE_LABELS) != 4:
        return _fail('opening schedule labels incomplete')
    if len(SCHEDULE_DISPLAY) < 9:
        return _fail('schedule display incomplete')

    if '/premarket' not in HELP_TEXT:
        return _fail('/premarket missing from help')
    if '/premarket full' not in HELP_TEXT.lower() and 'premarket full' not in HELP_TEXT.lower():
        return _fail('/premarket full missing from help')

    results = handle_analysis_command('/premarket', 'test', dry_run=True)
    result_upper = str(results[0].get('text', '')).upper() if results else ''
    if not results or not any(
        token in result_upper
        for token in ('PREMARKET', 'WEEKEND RESEARCH', 'LIVE MARKET WATCH')
    ):
        return _fail('/premarket command failed')
    results_full = handle_analysis_command('/premarket full', 'test', dry_run=True)
    if not results_full:
        return _fail('/premarket full command failed')

    print('PREMARKET_ALERTS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
