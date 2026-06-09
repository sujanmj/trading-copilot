#!/usr/bin/env python3
"""Unit tests — /full is read-only (Stage 48P)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'TELEGRAM_FULL_READONLY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram import telegram_analysis_bot as tab
    from backend.telegram.lazy_command_runner import FULL_SNAPSHOT_EXCLUDED, FULL_SNAPSHOT_SEQUENCE

    for excluded in FULL_SNAPSHOT_EXCLUDED:
        if excluded in FULL_SNAPSHOT_SEQUENCE:
            return _fail(f'read-only /full must not include {excluded}')

    refresh_calls: list[str] = []
    bootstrap_calls: list[int] = []
    broker_refresh_calls: list[bool] = []
    news_refresh_flags: list[bool] = []

    def _track_refresh(scope: str, *, dry_run: bool = False) -> dict:
        refresh_calls.append(scope)
        return {'ok': True, 'scope': scope}

    def _track_bootstrap(*args, **kwargs):
        bootstrap_calls.append(1)

    def _track_broker_refresh(*args, **kwargs):
        broker_refresh_calls.append(True)
        return {'ok': True}

    def _track_news_only(*, refresh: bool = True):
        news_refresh_flags.append(refresh)
        return {'ok': True, 'text': 'news stub'}

    with patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=_track_refresh):
        with patch('backend.telegram.telegram_analysis_bot.run_news_only', side_effect=_track_news_only):
            tab.handle_analysis_command('/news', 'test', dry_run=True, in_full_snapshot=True)
    if news_refresh_flags != [False]:
        return _fail(f'/news in snapshot must use refresh=False, got {news_refresh_flags!r}')

    def _snapshot_stub(text: str, from_user: str = 'unknown', *, dry_run: bool = False, in_full_snapshot: bool = False):
        if not in_full_snapshot:
            return _fail('expected in_full_snapshot') or []
        return [{'ok': True, 'text': f'stub:{text}'}]

    with patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=_track_refresh):
        with patch('backend.analytics.railway_decision_bootstrap.start_background_bootstrap_reports', side_effect=_track_bootstrap):
            with patch('backend.analytics.broker_intelligence.refresh_broker_intelligence', side_effect=_track_broker_refresh):
                with patch.object(tab, 'handle_analysis_command', side_effect=_snapshot_stub):
                    tab._handle_full_snapshot(dry_run=True)

    if bootstrap_calls:
        return _fail('/full must not start background bootstrap')
    if broker_refresh_calls:
        return _fail('/full must not refresh broker intelligence')
    if refresh_calls:
        return _fail(f'/full must not call scoped refresh, got {refresh_calls!r}')

    print('TELEGRAM_FULL_READONLY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
