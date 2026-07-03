#!/usr/bin/env python3
"""Phase 4B.10 — weekend/closed-market previous-session reference labeling."""

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
    print(f'OPENING_SESSION_WEEKEND_4B10_TEST_FAIL: {msg}', file=sys.stderr)
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


def _friday_scanner(*tickers: str) -> dict:
    return {
        'session_date': '2026-05-29',
        'scan_time_local': '2026-05-29 15:20:00',
        'top_signals': [_row(t) for t in tickers],
    }


def _same_day_scanner(*tickers: str, day: str = '2026-05-27') -> dict:
    return {
        'session_date': day,
        'scan_time_local': f'{day} 10:20:00',
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


def test_weekend_tradecards_previous_session_reference() -> int:
    from backend.telegram.response_format import format_tradecards_telegram

    board = _build_board(_dt(2026, 5, 30, 11, 0), _friday_scanner('PERSISTENT', 'COFORGE', 'INFY'))
    if board.get('data_status') != 'previous_session_reference':
        return _fail(f'weekend board must be previous_session_reference got {board.get("data_status")!r}')
    if not board.get('reference_only'):
        return _fail('weekend board must set reference_only')
    text = format_tradecards_telegram(board=board)
    if 'TOP CANDIDATES' in text:
        return _fail('weekend /tradecards must not show TOP CANDIDATES')
    if 'PREVIOUS-SESSION REFERENCE' not in text:
        return _fail('weekend /tradecards must show PREVIOUS-SESSION REFERENCE title')
    if 'Market lifecycle: WEEKEND' not in text:
        return _fail('weekend /tradecards must show Market lifecycle: WEEKEND')
    if 'Current IST:' not in text:
        return _fail('weekend /tradecards must show Current IST metadata')
    if 'PERSISTENT' in text and 'not current' not in text.lower():
        return _fail('weekend symbols must be labeled not current')
    return 0


def test_weekend_tradecard_no_current_entry() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.opening_rally_radar import select_synced_tradecard

    board = _build_board(_dt(2026, 5, 30, 11, 0), _friday_scanner('PERSISTENT', 'COFORGE'))
    sync = select_synced_tradecard(board=board, now=_dt(2026, 5, 30, 11, 0))
    if sync.get('selected'):
        return _fail('weekend /tradecard must not select a best pick')
    if not sync.get('reference_only'):
        return _fail('weekend sync must flag reference_only')

    legacy_card = {
        'ok': True,
        'ticker': 'PERSISTENT',
        'status': 'NO_ACTIVE_ENTRY',
        'reason': 'legacy',
        'paper_only': True,
    }
    with patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value=sync), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=legacy_card), \
         patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False), \
         patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value={}), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''):
        text = format_tradecard_telegram(explain=False, freshness_meta={}, chat_id='weekend-tradecard')
    if 'NO CURRENT ENTRY' not in text.upper():
        return _fail('weekend /tradecard must show NO CURRENT ENTRY')
    if 'PREVIOUS-SESSION REFERENCE' not in text:
        return _fail('weekend /tradecard must show PREVIOUS-SESSION REFERENCE title')
    return 0


def test_weekend_radar_not_current_pre_armed() -> int:
    from backend.telegram.response_format import format_opening_radar_telegram

    board = _build_board(_dt(2026, 5, 30, 11, 0), _friday_scanner('PERSISTENT'))
    text = format_opening_radar_telegram(board=board)
    if 'PREVIOUS-SESSION REFERENCE' not in text:
        return _fail('weekend /radar must show PREVIOUS-SESSION REFERENCE')
    if 'RADAR ARMED' in text and 'not current' not in text.lower():
        return _fail('weekend /radar must not show unlabeled pre-armed board')
    return 0


def test_weekend_gainers_previous_session_reference() -> int:
    from backend.telegram.response_format import format_all_cap_gainers_telegram
    from backend.trading.all_cap_gainers import scan_all_cap_gainers

    scanner = _friday_scanner('PERSISTENT', 'COFORGE')
    with patch('backend.trading.all_cap_gainers._load_json', return_value=scanner):
        scan = scan_all_cap_gainers(scanner_payload=scanner, now=_dt(2026, 5, 30, 11, 0))
    text = format_all_cap_gainers_telegram(gainer_scan=scan)
    if 'PREVIOUS-SESSION REFERENCE' not in text:
        return _fail('weekend /gainers must show PREVIOUS-SESSION REFERENCE')
    if 'Not current live gainers' not in text:
        return _fail('weekend /gainers must state not current live gainers')
    if 'Market lifecycle: WEEKEND' not in text:
        return _fail('weekend /gainers must show market lifecycle WEEKEND')
    return 0


def test_live_market_top_candidates() -> int:
    from backend.telegram.response_format import format_tradecards_telegram

    board = _build_board(_dt(2026, 5, 27, 10, 30), _same_day_scanner('PERSISTENT', 'COFORGE', day='2026-05-27'))
    if board.get('reference_only'):
        return _fail('live same-session board must not be reference_only')
    text = format_tradecards_telegram(board=board)
    if 'TOP CANDIDATES' not in text:
        return _fail('live /tradecards must show TOP CANDIDATES')
    if 'PREVIOUS-SESSION REFERENCE' in text:
        return _fail('live /tradecards must not show previous-session reference title')
    if 'Current IST:' not in text:
        return _fail('live /tradecards must include Current IST metadata')
    return 0


def test_multi_day_stale_still_blocked() -> int:
    from backend.telegram.response_format import format_tradecards_telegram

    old_scanner = {
        'session_date': '2026-05-20',
        'scan_time_local': '2026-05-20 10:00:00',
        'top_signals': [_row('PERSISTENT')],
    }
    board = _build_board(_dt(2026, 5, 30, 11, 0), old_scanner)
    if not board.get('session_stale'):
        return _fail('multi-day old board on weekend must be session_stale')
    text = format_tradecards_telegram(board=board)
    if 'STALE' not in text:
        return _fail('multi-day stale must show STALE title')
    if 'TOP CANDIDATES' in text:
        return _fail('multi-day stale must not show TOP CANDIDATES')
    return 0


def test_build_label_51l() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51M':
        return _fail(f'expected AstraEdge 51M got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_weekend_tradecards_previous_session_reference,
        test_weekend_tradecard_no_current_entry,
        test_weekend_radar_not_current_pre_armed,
        test_weekend_gainers_previous_session_reference,
        test_live_market_top_candidates,
        test_multi_day_stale_still_blocked,
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
    print(f'ALL {len(tests)} OPENING_SESSION_WEEKEND_4B10 TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
