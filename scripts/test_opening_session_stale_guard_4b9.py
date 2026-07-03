#!/usr/bin/env python3
"""Phase 4B.9 — session-date stale guard for opening workflow commands."""

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
    print(f'OPENING_SESSION_STALE_4B9_TEST_FAIL: {msg}', file=sys.stderr)
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


def _old_scanner(*tickers: str) -> dict:
    return {
        'session_date': '2026-07-04',
        'scan_time_local': '2026-07-04 01:20:00',
        'top_signals': [_row(t) for t in tickers],
    }


def _fresh_scanner(*tickers: str) -> dict:
    return {
        'session_date': '2026-07-07',
        'scan_time_local': '2026-07-07 09:25:00',
        'top_signals': [_row(t) for t in tickers],
    }


def test_stale_tradecards_blocked() -> int:
    from backend.telegram.response_format import format_tradecards_telegram
    from backend.trading.opening_rally_radar import build_opening_rally_board

    scanner = _old_scanner('PERSISTENT', 'COFORGE', 'INFY')
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
         patch('backend.trading.opening_rally_radar._load_json', return_value={}), \
         patch('backend.trading.opening_rally_radar.SCANNER_FILE', Path('scanner_data.json')):
        board = build_opening_rally_board(
            now=_dt(2026, 7, 7, 1, 30),
            catalyst_payload={},
            scanner_payload=scanner,
            premarket_payload={},
        )
    if not board.get('session_stale'):
        return _fail('board must be marked session_stale for old scanner date')
    text = format_tradecards_telegram(board=board)
    if 'TOP CANDIDATES' in text:
        return _fail('stale /tradecards must not show TOP CANDIDATES header')
    if 'STALE / PREVIOUS SESSION' not in text:
        return _fail('stale /tradecards must show STALE / PREVIOUS SESSION')
    if 'PERSISTENT' in text and 'Previous-session reference' not in text:
        return _fail('old symbols must appear only under previous-session reference')
    if '2026-07-07' not in text:
        return _fail('stale /tradecards must show current IST date')
    return 0


def test_stale_tradecard_does_not_select_best() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.opening_rally_radar import select_synced_tradecard

    scanner = _old_scanner('PERSISTENT', 'COFORGE')
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
         patch('backend.trading.opening_rally_radar._load_json', return_value={}):
        from backend.trading.opening_rally_radar import build_opening_rally_board

        board = build_opening_rally_board(
            now=_dt(2026, 7, 7, 1, 30),
            catalyst_payload={},
            scanner_payload=scanner,
            premarket_payload={},
        )
        sync = select_synced_tradecard(board=board, now=_dt(2026, 7, 7, 1, 30))
    if sync.get('selected'):
        return _fail(f'stale board must not select best pick got {sync.get("selected")!r}')
    if not sync.get('session_stale'):
        return _fail('sync must flag session_stale')

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
        text = format_tradecard_telegram(explain=False, freshness_meta={}, chat_id='stale-tradecard')
    if 'NO CURRENT-SESSION' not in text.upper():
        return _fail('/tradecard must report no current-session board')
    if 'TRADE CARD —' in text and 'PERSISTENT' in text and 'Previous-session reference' not in text:
        return _fail('stale /tradecard must not show PERSISTENT as active watch')
    return 0


def test_stale_radar_not_current() -> int:
    from backend.telegram.response_format import format_opening_radar_telegram
    from backend.trading.opening_rally_radar import build_opening_rally_board

    scanner = _old_scanner('INFY', 'ABFRL')
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
         patch('backend.trading.opening_rally_radar._load_json', return_value={}):
        board = build_opening_rally_board(
            now=_dt(2026, 7, 7, 1, 30),
            catalyst_payload={},
            scanner_payload=scanner,
            premarket_payload={},
        )
    text = format_opening_radar_telegram(board=board)
    if 'Opening Rally Radar —' in text and 'STALE' not in text and 'no current-date' not in text.lower():
        return _fail('stale /radar must not present old candidates as current')
    if '1. <b>INFY</b>' in text:
        return _fail('stale /radar must not rank old INFY as current candidate')
    return 0


def test_stale_gainers_warns() -> int:
    from backend.telegram.response_format import format_all_cap_gainers_telegram
    from backend.trading.all_cap_gainers import scan_all_cap_gainers

    scanner = _old_scanner('SONACOMS', 'VISL')
    scan = scan_all_cap_gainers(scanner_payload=scanner, now=_dt(2026, 7, 7, 1, 30))
    if not scan.get('session_stale'):
        return _fail('gainer scan must be session_stale')
    text = format_all_cap_gainers_telegram(gainer_scan=scan)
    if 'ALL-CAP GAINERS — live discovery' in text:
        return _fail('stale /gainers must not show live discovery header')
    if 'STALE / PREVIOUS SESSION' not in text:
        return _fail('stale /gainers must warn stale')
    return 0


def test_same_day_cache_works() -> int:
    from backend.telegram.response_format import format_tradecards_telegram
    from backend.trading.opening_rally_radar import build_opening_rally_board, pick_best_opening_tradecard

    scanner = _fresh_scanner('PERSISTENT', 'COFORGE')
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
         patch('backend.trading.opening_rally_radar._load_json', return_value={}):
        board = build_opening_rally_board(
            now=_dt(2026, 7, 7, 9, 25),
            catalyst_payload={},
            scanner_payload=scanner,
            premarket_payload={},
        )
    if board.get('session_stale'):
        return _fail('same-day scanner must not be stale')
    text = format_tradecards_telegram(board=board)
    if 'TOP CANDIDATES' not in text:
        return _fail('same-day /tradecards must show TOP CANDIDATES')
    best, score, _ = pick_best_opening_tradecard(board)
    if not best:
        return _fail(f'same-day board must pick best candidate got score={score}')
    return 0


def test_after_hours_same_date_next_session_ok() -> int:
    from backend.trading.tradecard_evidence import build_tradecard_evidence_matrix

    opening = {
        'ticker': 'PERSISTENT',
        'gainer_promoted': True,
        'sector_breadth': {'sector': 'IT', 'boost': 8},
        'tradecards_best': True,
        'from_board': True,
    }
    matrix = build_tradecard_evidence_matrix(
        'PERSISTENT',
        context={
            'scanner': {'top_signals': [_row('PERSISTENT')], 'session_date': '2026-07-07'},
            'opening_radar': opening,
            'market_mode': 'AFTER_HOURS',
        },
    )
    if matrix.get('decision') != 'NEXT-SESSION WATCH':
        return _fail(f'after-hours same-date must allow NEXT-SESSION WATCH got {matrix.get("decision")!r}')
    return 0


def test_learning_capture_skipped_when_stale() -> int:
    from io import StringIO
    from contextlib import redirect_stdout
    from backend.trading.opening_rally_radar import build_opening_rally_board

    scanner = _old_scanner('PERSISTENT')
    buf = StringIO()
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
         patch('backend.trading.opening_rally_radar._load_json', return_value={}), \
         redirect_stdout(buf):
        build_opening_rally_board(
            now=_dt(2026, 7, 7, 1, 30),
            catalyst_payload={},
            scanner_payload=scanner,
            premarket_payload={},
        )
    logs = buf.getvalue()
    if '[MULTI_TRADECARD_RANK]' in logs:
        return _fail('stale board must not log MULTI_TRADECARD_RANK as current learning')
    if '[OPENING_SESSION_STALE]' not in logs:
        return _fail('stale board must log OPENING_SESSION_STALE')
    return 0


def main() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51J':
        return _fail(f'expected AstraEdge 51J got {ASTRAEDGE_TELEGRAM_BUILD!r}')

    tests = (
        test_stale_tradecards_blocked,
        test_stale_tradecard_does_not_select_best,
        test_stale_radar_not_current,
        test_stale_gainers_warns,
        test_same_day_cache_works,
        test_after_hours_same_date_next_session_ok,
        test_learning_capture_skipped_when_stale,
    )
    for test_fn in tests:
        rc = test_fn()
        if rc:
            return rc
    print('OPENING_SESSION_STALE_4B9_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
