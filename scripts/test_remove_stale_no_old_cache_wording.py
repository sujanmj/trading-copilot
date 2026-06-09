#!/usr/bin/env python3
"""Unit tests — remove Stale: no / old cache wording (Stage 48T)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

FORBIDDEN = ('Stale: no', 'cache age: old cache', 'old cache ·')


def _fail(msg: str) -> int:
    print(f'REMOVE_STALE_NO_OLD_CACHE_WORDING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _assert_clean(label: str, text: str) -> int | None:
    for needle in FORBIDDEN:
        if needle in text:
            return _fail(f'{label} must not contain {needle!r}')
    if 'Report:' not in text and 'report' not in text.lower():
        return _fail(f'{label} missing standard report freshness line')
    return None


def main() -> int:
    from backend.telegram.lazy_command_runner import run_market_only
    from backend.telegram.response_format import strip_stage_markers
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text, build_morning_brief_text

    meta = {
        'report_age_min': 960,
        'scanner_age_min': 45,
        'report_stale': True,
        'lines': {
            'report': 'Report: stale · 16h',
            'scanner': 'Scanner: fresh · 45m',
            'news': 'Latest news cache: stale · 12h',
        },
    }

    with patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value=meta), patch(
        'backend.telegram.lazy_command_runner.run_global_only',
        return_value={'text': 'Global ok'},
    ), patch(
        'backend.telegram.lazy_command_runner.run_market_only',
        wraps=run_market_only,
    ), patch(
        'backend.analytics.aihub_tab_payloads.build_market_payload',
        return_value={'market_mode': 'INDIA_AFTER_HOURS', 'summary': {}, 'cache_age_seconds': 3600, 'source': 'cache'},
    ), patch(
        'backend.telegram.telegram_brief_scheduler._build_today_tomorrow_text',
        return_value='Today ok',
    ), patch(
        'backend.telegram.lazy_command_runner.run_daily_pack_only',
        return_value={'text': 'Pack ok'},
    ), patch(
        'backend.telegram.lazy_command_runner.run_memory_only',
        return_value={'text': 'Memory ok'},
    ):
        morning = strip_stage_markers(build_morning_brief_text())
        close = strip_stage_markers(build_close_brief_text())
        market = strip_stage_markers(run_market_only().get('text') or '')

    for label, text in (('morning', morning), ('close', close), ('market', market)):
        err = _assert_clean(label, text)
        if err:
            return err

    with patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value=meta):
        from backend.telegram.response_format import format_aihub_full

        full_text = strip_stage_markers(format_aihub_full({'calib': {'summary': {}}, 'journal': {'summary': {}}}))
    for needle in FORBIDDEN:
        if needle in full_text:
            return _fail(f'/aihub full must not contain {needle!r}')

    print('REMOVE_STALE_NO_OLD_CACHE_WORDING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
