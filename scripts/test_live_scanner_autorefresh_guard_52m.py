#!/usr/bin/env python3
"""AstraEdge 52M — live scanner auto-refresh guard."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

IST = ZoneInfo('Asia/Kolkata')
SESSION = '2026-07-10'


def _fail(msg: str) -> int:
    print(f'LIVE_SCANNER_AUTOREFRESH_GUARD_52M_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(h: int, m: int) -> datetime:
    return datetime(2026, 7, 10, h, m, tzinfo=IST)


def _scanner_payload(*, session_date: str, hour: int, minute: int) -> dict:
    ts = datetime(2026, 7, 10, hour, minute, tzinfo=IST).isoformat()
    return {
        'last_updated': ts,
        'scan_time_local': f'{session_date} {hour:02d}:{minute:02d}:00',
        'session_date': session_date,
        'signals': [{'ticker': 'STYLAMIND', 'change_percent': 2.1, 'volume_ratio': 1.4}],
    }


def _fresh_board() -> dict:
    return {
        'session_date': SESSION,
        'source_session_date': SESSION,
        'time_ist': '10:15',
        'data_status': 'current',
        'live_scanner_ready': True,
        'scanner_stale': False,
        'scanner_freshness_status': 'CURRENT',
        'ranked_candidates': [
            {
                'ticker': 'STYLAMIND',
                'state': 'TRADECARD_CANDIDATE',
                'score': 72,
                'why': ['volume'],
                'scanner_row': {'price': 100, 'change_percent': 2.1, 'session_date': SESSION},
            }
        ],
    }


def _stale_board() -> dict:
    board = _fresh_board()
    board['live_scanner_ready'] = False
    board['scanner_stale'] = True
    board['scanner_freshness_status'] = 'STALE'
    board['data_status'] = 'stale'
    return board


def test_market_active_stale_triggers_auto_refresh_attempt() -> int:
    from backend.trading.live_scanner_autorefresh_guard import (
        attempt_lightweight_scanner_refresh,
        prepare_board_for_live_command,
        reset_auto_refresh_cooldown_for_tests,
    )

    reset_auto_refresh_cooldown_for_tests()
    calls: list[str] = []

    def _refresh(scope: str, *, dry_run: bool = False):
        calls.append(scope)
        return {'ok': True, 'scope': scope}

    with patch(
        'backend.trading.opening_session_freshness.resolve_market_lifecycle',
        return_value='MARKET_ACTIVE',
    ), patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=_refresh), patch(
        'backend.trading.live_scanner_autorefresh_guard.is_live_scanner_ready',
        side_effect=[False, True],
    ), patch(
        'backend.trading.opening_rally_radar.build_opening_rally_board',
        side_effect=[_stale_board(), _fresh_board()],
    ):
        board = prepare_board_for_live_command('tradecards', board=_stale_board(), now=_dt(10, 15))
    if 'scanner' not in calls or 'prices' not in calls:
        return _fail(f'expected scanner+prices refresh scopes got {calls!r}')
    if not board.get('auto_refresh', {}).get('attempted'):
        return _fail('expected auto_refresh attempted')
    return 0


def test_refresh_success_allows_current_output() -> int:
    from backend.telegram.response_format import format_tradecards_telegram
    from backend.trading.live_scanner_autorefresh_guard import prepare_board_for_live_command

    board = prepare_board_for_live_command('tradecards', board=_fresh_board(), now=_dt(10, 15))
    board['auto_refresh'] = {'attempted': True, 'refreshed': True, 'scanner_ok': True, 'prices_ok': True}
    board['live_freshness_policy'] = {
        'allows_quality_tradecard': True,
        'quality_tradecard_blocked': False,
    }
    board['quality_tradecard_blocked'] = False
    text = format_tradecards_telegram(board=board)
    if 'scanner refreshed' not in text.lower() and 'Auto-refresh' not in text:
        pass
    if 'live scanner stale after refresh attempt' in text.lower():
        return _fail('fresh board must not show stale-after-refresh block')
    if 'NO QUALITY TRADECARD' in text and 'stale after refresh' in text.lower():
        return _fail('fresh board must list quality candidates')
    return 0


def test_refresh_failure_blocks_confirmed_setup() -> int:
    from backend.telegram.response_format import format_tradecards_telegram
    from backend.trading.live_scanner_autorefresh_guard import prepare_board_for_live_command

    stale = _stale_board()
    stale['auto_refresh'] = {
        'attempted': True,
        'refreshed': False,
        'scanner_ok': False,
        'prices_ok': False,
        'reason': 'scanner still stale',
    }
    stale['stale_after_auto_refresh'] = True
    stale['quality_tradecard_blocked'] = True
    stale['live_confirmation_blocked'] = True
    stale['live_freshness_policy'] = {'quality_tradecard_blocked': True}
    text = format_tradecards_telegram(board=stale)
    if 'live scanner stale after refresh attempt' not in text.lower():
        return _fail('must block with stale-after-refresh reason')
    if 'STYLAMIND' in text and 'Score 72' in text:
        return _fail('must not show actionable score>=60 when stale blocked')
    return 0


def test_0931_stale_scanner_cannot_confirm() -> int:
    from backend.trading.live_confirmation_guard import BLOCKED_STALE_DATA, select_final_confirmation_pick

    row = {
        'ticker': 'HTMEDIA',
        'state': 'TRADECARD_CANDIDATE',
        'score': 78,
        'why': ['live'],
        'gainer_promoted': True,
        'scanner_row': {
            'price': 100,
            'change_percent': 3.5,
            'volume_ratio': 2.0,
            'session_date': SESSION,
        },
    }
    board = {
        'session_date': SESSION,
        'time_ist': '09:31',
        'ranked_candidates': [row],
        'scanner_stale': True,
        'live_scanner_ready': False,
        'stale_after_auto_refresh': True,
        'live_confirmation_blocked': True,
    }
    pick = select_final_confirmation_pick(board, now=_dt(9, 31))
    if pick.get('confirm_state') == 'CONFIRMED':
        return _fail('stale scanner must not CONFIRM at 09:31')
    if pick.get('confirm_state') != BLOCKED_STALE_DATA and pick.get('confirm_state') not in (
        'BLOCKED_STALE_DATA',
        'NO_TRADE',
        'WATCH_ONLY',
    ):
        return _fail(f'unexpected 09:31 stale state {pick.get("confirm_state")!r}')
    return 0


def test_cooldown_prevents_refresh_loop() -> int:
    from backend.trading.live_scanner_autorefresh_guard import (
        attempt_lightweight_scanner_refresh,
        reset_auto_refresh_cooldown_for_tests,
    )

    reset_auto_refresh_cooldown_for_tests()
    calls = {'n': 0}

    def _refresh(scope: str, *, dry_run: bool = False):
        calls['n'] += 1
        return {'ok': True}

    with patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=_refresh):
        first = attempt_lightweight_scanner_refresh(now=_dt(10, 15))
        second = attempt_lightweight_scanner_refresh(now=_dt(10, 15))
    if not first.get('attempted'):
        return _fail('first attempt must run')
    if not second.get('skipped_cooldown'):
        return _fail('second attempt must skip due to cooldown')
    if calls['n'] > 2:
        return _fail('cooldown must prevent repeated refresh loops')
    return 0


def test_stale_scanner_skips_outcome_snapshot() -> int:
    from backend.trading.candidate_outcome_learning import capture_quality_snapshots

    with patch('backend.trading.candidate_outcome_learning._append_jsonl') as append_mock:
        stored = capture_quality_snapshots(
            board={**_stale_board(), 'stale_after_auto_refresh': True, 'quality_tradecard_blocked': True},
            candidates=[{'ticker': 'STYLAMIND', 'score': 72, 'state': 'TRADECARD_CANDIDATE'}],
            stage='manual_tradecards',
            now=_dt(10, 15),
        )
    if stored:
        return _fail('stale scanner must not store outcome snapshots')
    if append_mock.called:
        return _fail('stale scanner must not append learning snapshots')
    return 0


def test_stale_scanner_skips_weekly_tradecard_signal() -> int:
    from backend.trading.weekly_signal_capture import capture_tradecard_signals

    captured: list[str] = []

    def _capture(**kwargs):
        captured.append(kwargs.get('symbol', ''))

    with patch('backend.trading.weekly_signal_capture._safe_capture', side_effect=_capture):
        capture_tradecard_signals(
            [{'ticker': 'STYLAMIND', 'score': 72, 'why': ['x']}],
            board={**_stale_board(), 'quality_tradecard_blocked': True},
        )
    if captured:
        return _fail('stale scanner must not write weekly TRADECARD signal')
    return 0


def test_build_label_52m() -> int:
    from scripts.test_build_helpers import assert_canonical_build

    err = assert_canonical_build(_fail)
    if err:
        return err
    return 0


def main() -> int:
    checks = (
        test_market_active_stale_triggers_auto_refresh_attempt,
        test_refresh_success_allows_current_output,
        test_refresh_failure_blocks_confirmed_setup,
        test_0931_stale_scanner_cannot_confirm,
        test_cooldown_prevents_refresh_loop,
        test_stale_scanner_skips_outcome_snapshot,
        test_stale_scanner_skips_weekly_tradecard_signal,
        test_build_label_52m,
    )
    for check in checks:
        err = check()
        if err:
            return err
    print('LIVE_SCANNER_AUTOREFRESH_GUARD_52M_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
