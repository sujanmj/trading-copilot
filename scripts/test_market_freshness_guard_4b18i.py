#!/usr/bin/env python3
"""Phase 4B.18I — Market freshness guard + opening scanner refresh (AstraEdge 52G)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
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
SESSION = '2026-07-09'


def _fail(msg: str) -> int:
    print(f'MARKET_FRESHNESS_GUARD_4B18I_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(h: int, m: int) -> datetime:
    return datetime(2026, 7, 9, h, m, tzinfo=IST)


def _scanner_payload(*, session_date: str, hour: int, minute: int) -> dict:
    ts = datetime(2026, 7, 9, hour, minute, tzinfo=IST).isoformat()
    return {
        'last_updated': ts,
        'scan_time_local': f'{session_date} {hour:02d}:{minute:02d}:00',
        'session_date': session_date,
        'signals': [{'ticker': 'BALAMINES', 'change_percent': 6.2, 'volume_ratio': 8.8}],
    }


@contextmanager
def _data_dir():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp)
        yield data


def test_board_wrapper_stale_when_scanner_old_date() -> int:
    from backend.trading.market_freshness_guard import (
        apply_market_freshness_to_board,
        composite_data_status,
        evaluate_all_source_freshness,
    )

    with _data_dir() as data_dir:
        scanner_path = data_dir / 'scanner_data.json'
        scanner_path.write_text(
            json.dumps(_scanner_payload(session_date='2026-07-08', hour=15, minute=30)),
            encoding='utf-8',
        )
        with patch('backend.trading.market_freshness_guard.SCANNER_FILE', scanner_path), patch(
            'backend.trading.opening_session_freshness.resolve_market_lifecycle',
            return_value='MARKET_ACTIVE',
        ):
            board = {
                'generated_at': _dt(9, 20).isoformat(),
                'data_status': 'current',
                'source_session_date': SESSION,
                'ranked_candidates': [{'ticker': 'BALAMINES', 'score': 70, 'state': 'RADAR_ARMED'}],
            }
            out = apply_market_freshness_to_board(board, now=_dt(9, 20))
            table = evaluate_all_source_freshness(board=out, now=_dt(9, 20))
            composite = composite_data_status(
                wrapper_status='current',
                freshness_table=table,
                now=_dt(9, 20),
            )
    if out.get('data_status') == 'current' and composite == 'current':
        return _fail('expected stale composite when scanner source is old date')
    if str((table.get('scanner') or {}).get('freshness_status')) not in (
        'PREVIOUS_SESSION', 'STALE', 'MISSING',
    ):
        return _fail(f'unexpected scanner status {table.get("scanner")!r}')
    return 0


def test_0920_radar_excludes_stale_previous_session_movers() -> int:
    from backend.trading.market_freshness_guard import filter_stale_live_candidates

    ranked = [
        {'ticker': 'BALAMINES', 'previous_mover': True, 'score': 70, 'state': 'RADAR_ARMED'},
        {'ticker': 'HTMEDIA', 'previous_mover': False, 'scanner_row': {'price': 100}, 'score': 80},
    ]
    with patch(
        'backend.trading.opening_session_freshness.resolve_market_lifecycle',
        return_value='MARKET_ACTIVE',
    ):
        kept = filter_stale_live_candidates(ranked, live_scanner_ready=False, now=_dt(9, 20))
    syms = {str(r.get('ticker')) for r in kept}
    if 'BALAMINES' in syms:
        return _fail('stale previous-session mover should be excluded')
    if 'HTMEDIA' not in syms:
        return _fail('live scanner row candidate should remain')
    return 0


def test_0920_scanner_stale_message() -> int:
    from backend.trading.market_freshness_guard import format_scanner_stale_radar_telegram

    text = format_scanner_stale_radar_telegram(
        {'scanner_stale': True, 'data_status': 'stale', 'time_ist': '09:20'},
    )
    if 'SCANNER STALE' not in text and 'WAIT' not in text:
        return _fail(f'missing SCANNER STALE/WAIT: {text[:120]!r}')
    return 0


def test_0925_no_active_tradecard_when_scanner_missing() -> int:
    from backend.trading.market_freshness_guard import format_no_active_tradecard_telegram

    text = format_no_active_tradecard_telegram({'scanner_stale': True, 'data_status': 'stale'})
    if 'NO ACTIVE TRADECARD' not in text:
        return _fail('missing NO ACTIVE TRADECARD message')
    return 0


def test_0931_no_trade_when_scanner_before_0915() -> int:
    from backend.trading.live_confirmation_guard import NO_TRADE, evaluate_live_confirmation

    board = {
        'data_status': 'current',
        'live_scanner_ready': False,
        'scanner_stale': True,
        'ranked_candidates': [],
    }
    row = {
        'ticker': 'HTMEDIA',
        'state': 'TRADECARD_CANDIDATE',
        'score': 78,
        'scanner_row': {'price': 100, 'change_percent': 2.0, 'session_date': SESSION},
        'has_catalyst': True,
        'catalyst': {'published_at': _dt(9, 0).isoformat(), 'freshness_label': 'today'},
    }
    with patch(
        'backend.trading.market_freshness_guard.is_scanner_ready_for_final_confirm',
        return_value=(False, 'scanner before 09:15 IST'),
    ):
        verdict = evaluate_live_confirmation(row, now=_dt(9, 31), board=board)
    if verdict.get('state') != NO_TRADE:
        return _fail(f'expected NO_TRADE got {verdict.get("state")!r}')
    return 0


def test_fresh_scanner_after_0915_allows_evaluation() -> int:
    from backend.trading.market_freshness_guard import is_live_scanner_ready

    payload = _scanner_payload(session_date=SESSION, hour=9, minute=18)
    with patch(
        'backend.trading.opening_session_freshness.resolve_market_lifecycle',
        return_value='MARKET_ACTIVE',
    ):
        ready = is_live_scanner_ready(scanner_payload=payload, now=_dt(9, 20))
    if not ready:
        return _fail('expected live scanner ready for 09:18 stamp at 09:20')
    return 0


def test_premarket_previous_session_labeled() -> int:
    from backend.trading.market_freshness_guard import FRESHNESS_PREOPEN_ONLY, _evaluate_scanner_freshness

    payload = _scanner_payload(session_date='2026-07-08', hour=16, minute=0)
    with patch(
        'backend.trading.opening_session_freshness.resolve_market_lifecycle',
        return_value='PRE_MARKET',
    ):
        rec = _evaluate_scanner_freshness(payload, now=_dt(8, 15))
    if rec.get('freshness_status') != FRESHNESS_PREOPEN_ONLY:
        return _fail(f'expected PREOPEN_ONLY got {rec.get("freshness_status")!r}')
    return 0


def test_refresh_scanner_command_exists() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    if '/refresh scanner' not in HELP_TEXT:
        return _fail('help missing /refresh scanner')
    return 0


def test_refresh_status_shows_table() -> int:
    from backend.trading.market_freshness_guard import format_freshness_status_telegram

    text = format_freshness_status_telegram(now=_dt(9, 20))
    if 'SOURCE FRESHNESS' not in text:
        return _fail('missing SOURCE FRESHNESS header')
    if 'scanner:' not in text.lower():
        return _fail('missing scanner row')
    return 0


def test_board_not_current_when_sources_stale() -> int:
    from backend.trading.market_freshness_guard import apply_market_freshness_to_board

    with _data_dir() as data_dir:
        scanner_path = data_dir / 'scanner_data.json'
        scanner_path.write_text(
            json.dumps(_scanner_payload(session_date='2026-07-08', hour=15, minute=0)),
            encoding='utf-8',
        )
        with patch('backend.trading.market_freshness_guard.SCANNER_FILE', scanner_path), patch(
            'backend.trading.opening_session_freshness.resolve_market_lifecycle',
            return_value='MARKET_ACTIVE',
        ):
            out = apply_market_freshness_to_board(
                {'generated_at': _dt(9, 20).isoformat(), 'data_status': 'current'},
                now=_dt(9, 20),
            )
    if out.get('data_status') == 'current':
        return _fail('board data_status should not remain current with stale scanner')
    return 0


def test_macro_red_market_guard_still_works() -> int:
    from backend.trading.live_confirmation_guard import NO_TRADE, evaluate_live_confirmation

    board = {
        'data_status': 'current',
        'live_scanner_ready': True,
        'scanner_stale': False,
        'emergency_macro': True,
        'macro_crash': True,
        'macro_penalty': 15,
    }
    row = {
        'ticker': 'BEL',
        'state': 'TRADECARD_CANDIDATE',
        'score': 72,
        'has_catalyst': True,
        'catalyst': {
            'published_at': '2026-07-07T08:00:00+05:30',
            'freshness_label': 'previous_day',
        },
    }
    with patch(
        'backend.trading.market_freshness_guard.is_scanner_ready_for_final_confirm',
        return_value=(True, ''),
    ), patch(
        'backend.trading.live_confirmation_guard.emergency_macro_crash_active',
        return_value=True,
    ):
        verdict = evaluate_live_confirmation(row, now=_dt(9, 31), board=board)
    if verdict.get('state') == 'CONFIRMED':
        return _fail('macro crash should block blind CONFIRMED on stale catalyst')
    if verdict.get('state') not in (NO_TRADE, 'WAIT_LIVE_CONFIRM'):
        return _fail(f'unexpected state {verdict.get("state")!r}')
    return 0


def _run(script: str) -> int:
    env = os.environ.copy()
    env.setdefault('ASTRAEDGE_QA_SMOKE', '1')
    env['DISABLE_TELEGRAM'] = '1'
    env['DISABLE_TELEGRAM_SENDS'] = '1'
    env['PYTHONPATH'] = str(PROJECT_ROOT)
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / script)],
        cwd=str(PROJECT_ROOT),
        env=env,
        check=False,
    ).returncode


def test_regression_feed_remove_4b18h() -> int:
    if _run('test_feed_remove_4b18h.py') != 0:
        return _fail('52F feed remove regression failed')
    return 0


def test_regression_feed_ticker_resolver_4b18g() -> int:
    if _run('test_feed_ticker_resolver_4b18g.py') != 0:
        return _fail('52E feed ticker resolver regression failed')
    return 0


def test_regression_macro_emergency_4b18f() -> int:
    if _run('test_macro_emergency_persistence_4b18f.py') != 0:
        return _fail('52D macro emergency regression failed')
    return 0


def test_regression_live_confirmation_4b18d() -> int:
    if _run('test_live_confirmation_guard_4b18d.py') != 0:
        return _fail('52B live confirmation regression failed')
    return 0


def test_build_label_52g() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52G' or ASTRAEDGE_BUILD_STAGE != '52G':
        return _fail(f'expected AstraEdge 52G got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_board_wrapper_stale_when_scanner_old_date,
        test_0920_radar_excludes_stale_previous_session_movers,
        test_0920_scanner_stale_message,
        test_0925_no_active_tradecard_when_scanner_missing,
        test_0931_no_trade_when_scanner_before_0915,
        test_fresh_scanner_after_0915_allows_evaluation,
        test_premarket_previous_session_labeled,
        test_refresh_scanner_command_exists,
        test_refresh_status_shows_table,
        test_board_not_current_when_sources_stale,
        test_macro_red_market_guard_still_works,
        test_regression_feed_remove_4b18h,
        test_regression_feed_ticker_resolver_4b18g,
        test_regression_macro_emergency_4b18f,
        test_regression_live_confirmation_4b18d,
        test_build_label_52g,
    ]
    failed = 0
    for test in tests:
        rc = test()
        if rc:
            failed += 1
            print(f'FAIL: {test.__name__}', file=sys.stderr)
        else:
            print(f'OK: {test.__name__}')
    if failed:
        print(f'FAILED: {failed}/{len(tests)}', file=sys.stderr)
        return 1
    print('MARKET_FRESHNESS_GUARD_4B18I_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
