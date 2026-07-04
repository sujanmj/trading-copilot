#!/usr/bin/env python3
"""Phase 4B.11 — hard closed-market override + runtime IST clock sanity."""

from __future__ import annotations

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


def _fail(msg: str) -> int:
    print(f'OPENING_SESSION_HARD_CLOSED_4B11_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(y: int, m: int, d: int, hour: int, minute: int) -> datetime:
    return datetime(y, m, d, hour, minute, tzinfo=IST)


def _row(ticker: str, chg: float = 3.5, vol: float = 1.2) -> dict:
    return {
        'ticker': ticker,
        'change_percent': chg,
        'volume_ratio': vol,
        'price': 500.0,
        'open_price': 480.0,
        'vwap': 490.0,
        'direction': 'BULLISH',
    }


def _weekend_same_date_scanner(*tickers: str) -> dict:
    """Bug scenario: board session date equals weekend calendar date."""
    return {
        'session_date': '2026-07-04',
        'scan_time_local': '2026-07-04 02:05:00',
        'top_signals': [_row(t) for t in tickers],
    }


def _build_board(now: datetime, scanner: dict) -> dict:
    from backend.trading.opening_rally_radar import build_opening_rally_board

    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
         patch('backend.trading.opening_rally_radar._load_json', return_value={}):
        return build_opening_rally_board(
            now=now,
            catalyst_payload={},
            scanner_payload=scanner,
            premarket_payload={},
        )


def test_weekend_same_date_not_current() -> int:
    from backend.trading.opening_session_freshness import evaluate_data_status

    status = evaluate_data_status('2026-07-04', now=_dt(2026, 7, 4, 2, 5))
    if status != 'previous_session_reference':
        return _fail(f'weekend same-date must be previous_session_reference got {status!r}')
    return 0


def test_weekend_same_date_tradecards_not_top_candidates() -> int:
    from backend.telegram.response_format import format_tradecards_telegram

    board = _build_board(_dt(2026, 7, 4, 2, 5), _weekend_same_date_scanner('PERSISTENT', 'COFORGE'))
    if board.get('data_status') == 'current':
        return _fail('weekend same-date board must not be data_status=current')
    if not board.get('no_current_entry'):
        return _fail('weekend same-date board must set no_current_entry')
    text = format_tradecards_telegram(board=board)
    if 'TOP CANDIDATES' in text:
        return _fail('weekend same-date /tradecards must not show TOP CANDIDATES')
    if 'PREVIOUS-SESSION REFERENCE' not in text:
        return _fail('weekend same-date /tradecards must show PREVIOUS-SESSION REFERENCE')
    if 'Data status: previous-session reference' not in text:
        return _fail('weekend same-date must show previous-session reference data status')
    if 'Market lifecycle: WEEKEND' not in text:
        return _fail('weekend same-date must show Market lifecycle: WEEKEND')
    return 0


def test_weekend_same_date_tradecard_no_current_entry() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.opening_rally_radar import select_synced_tradecard

    board = _build_board(_dt(2026, 7, 4, 2, 5), _weekend_same_date_scanner('PERSISTENT'))
    sync = select_synced_tradecard(board=board, now=_dt(2026, 7, 4, 2, 5))
    if sync.get('selected'):
        return _fail('weekend same-date must not select tradecard')
    legacy = {'ok': True, 'ticker': 'PERSISTENT', 'status': 'NO_ACTIVE_ENTRY', 'reason': 'legacy', 'paper_only': True}
    with patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value=sync), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=legacy), \
         patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False), \
         patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value={}), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''):
        text = format_tradecard_telegram(explain=False, freshness_meta={}, chat_id='weekend-same-date')
    if 'NO CURRENT ENTRY' not in text.upper():
        return _fail('weekend same-date /tradecard must show NO CURRENT ENTRY')
    if 'NEXT-SESSION WATCH' in text:
        return _fail('weekend same-date /tradecard must not show NEXT-SESSION WATCH')
    return 0


def test_weekend_radar_and_gainers_reference() -> int:
    from backend.telegram.response_format import format_all_cap_gainers_telegram, format_opening_radar_telegram
    from backend.trading.all_cap_gainers import scan_all_cap_gainers

    now = _dt(2026, 7, 4, 2, 5)
    scanner = _weekend_same_date_scanner('PERSISTENT')
    board = _build_board(now, scanner)
    radar = format_opening_radar_telegram(board=board)
    if 'PREVIOUS-SESSION REFERENCE' not in radar:
        return _fail('weekend /radar must show PREVIOUS-SESSION REFERENCE')
    if 'No current live radar' not in radar:
        return _fail('weekend /radar must say no current live radar')
    scan = scan_all_cap_gainers(scanner_payload=scanner, now=now)
    gainers = format_all_cap_gainers_telegram(gainer_scan=scan)
    if 'PREVIOUS-SESSION REFERENCE' not in gainers:
        return _fail('weekend /gainers must show PREVIOUS-SESSION REFERENCE')
    if 'Not current live gainers' not in gainers:
        return _fail('weekend /gainers must say not current live gainers')
    return 0


def test_live_same_date_top_candidates() -> int:
    from backend.telegram.response_format import format_tradecards_telegram

    scanner = {
        'session_date': '2026-05-27',
        'scan_time_local': '2026-05-27 10:20:00',
        'top_signals': [_row('PERSISTENT'), _row('COFORGE')],
    }
    board = _build_board(_dt(2026, 5, 27, 10, 30), scanner)
    if board.get('reference_only'):
        return _fail('live same-date must not be reference_only')
    text = format_tradecards_telegram(board=board)
    if 'TOP CANDIDATES' not in text:
        return _fail('live same-date must show TOP CANDIDATES')
    return 0


def test_clock_uses_runtime_not_board_generated_at() -> int:
    from backend.trading.ist_clock import format_clock_telegram, runtime_clock_snapshot
    from backend.trading.opening_session_freshness import format_session_metadata_block

    board_time = '2026-07-04 02:05 IST'
    runtime_now = _dt(2026, 7, 7, 9, 0)
    board = {
        'market_lifecycle': 'WEEKEND',
        'source_session_date': '2026-07-04',
        'board_session_date': '2026-07-04',
        'data_status': 'previous_session_reference',
        'current_ist_display': board_time,
        'generated_at_display': board_time,
    }
    with patch('backend.trading.ist_clock.runtime_ist_now', return_value=runtime_now), \
         patch('backend.trading.opening_session_freshness.runtime_ist_display', return_value='2026-07-07 09:00 IST'):
        meta = format_session_metadata_block(board)
    ist_line = next((line for line in meta if line.startswith('Current IST:')), '')
    if board_time in ist_line:
        return _fail('metadata Current IST must not reuse board generated_at')
    if '2026-07-07 09:00 IST' not in ist_line:
        return _fail(f'metadata must show runtime IST got {ist_line!r}')
    snap = runtime_clock_snapshot(now=runtime_now)
    if snap.get('clock_source') != 'runtime':
        return _fail('clock snapshot must use runtime source')
    if snap.get('timezone_source') != 'Asia/Kolkata':
        return _fail('clock snapshot must use Asia/Kolkata timezone source')
    with patch('backend.trading.ist_clock.runtime_ist_now', return_value=runtime_now):
        clock_text = format_clock_telegram(now=runtime_now)
    if 'Clock source: <code>runtime</code>' not in clock_text:
        return _fail('/clock must show runtime clock source')
    return 0


def test_build_label_51l() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51N':
        return _fail(f'expected AstraEdge 51N got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_weekend_same_date_not_current,
        test_weekend_same_date_tradecards_not_top_candidates,
        test_weekend_same_date_tradecard_no_current_entry,
        test_weekend_radar_and_gainers_reference,
        test_live_same_date_top_candidates,
        test_clock_uses_runtime_not_board_generated_at,
        test_build_label_51l,
    ]
    failed = 0
    for test in tests:
        rc = test()
        if rc:
            failed += 1
        else:
            print(f'OK: {test.__name__}')
    if failed:
        print(f'FAILED: {failed}/{len(tests)}', file=sys.stderr)
        return 1
    print(f'ALL {len(tests)} OPENING_SESSION_HARD_CLOSED_4B11 TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
