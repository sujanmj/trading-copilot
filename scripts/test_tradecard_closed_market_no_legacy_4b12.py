#!/usr/bin/env python3
"""Phase 4B.12 — closed-market /tradecard must not use legacy fallback symbol."""

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
    print(f'TRADECARD_CLOSED_MARKET_4B12_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(y: int, m: int, d: int, hour: int, minute: int) -> datetime:
    return datetime(y, m, d, hour, minute, tzinfo=IST)


def _row(ticker: str, chg: float = 3.5, vol: float = 1.2, score: int = 70) -> dict:
    return {
        'ticker': ticker,
        'change_percent': chg,
        'volume_ratio': vol,
        'price': 500.0,
        'open_price': 480.0,
        'vwap': 490.0,
        'direction': 'BULLISH',
        'state': 'TOP_GAINER_CONFIRM',
        'score': score,
        'why': ['top large cap gainer'],
    }


def _weekend_scanner(*tickers: str) -> dict:
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


def test_closed_market_shows_reference_best_not_legacy() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.opening_rally_radar import select_synced_tradecard

    now = _dt(2026, 7, 4, 2, 5)
    board = _build_board(now, _weekend_scanner('PERSISTENT', 'COFORGE'))
    sync = select_synced_tradecard(board=board, now=now, legacy_ticker='CEATLTD')
    if sync.get('selected'):
        return _fail('closed-market sync must not select legacy/active ticker')
    if sync.get('reference_best') != 'PERSISTENT':
        return _fail(f'expected reference_best PERSISTENT got {sync.get("reference_best")!r}')

    legacy_card = {
        'ok': True,
        'ticker': 'CEATLTD',
        'status': 'NO_ACTIVE_ENTRY',
        'reason': 'legacy engine pick',
        'paper_only': True,
    }
    with patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value=sync), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=legacy_card), \
         patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False), \
         patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value={}), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''):
        text = format_tradecard_telegram(explain=False, freshness_meta={}, chat_id='weekend-ref')
    if 'CEATLTD' in text:
        return _fail('closed-market /tradecard must not show legacy CEATLTD')
    if 'PERSISTENT' not in text:
        return _fail('closed-market /tradecard must show previous-session best PERSISTENT')
    if 'NO CURRENT ENTRY' not in text.upper():
        return _fail('closed-market /tradecard must show NO CURRENT ENTRY')
    if 'not an active watch' not in text.lower():
        return _fail('closed-market /tradecard must label reference as not active watch')
    return 0


def test_closed_market_empty_board_no_symbol() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.opening_rally_radar import select_synced_tradecard

    now = _dt(2026, 7, 4, 2, 5)
    empty_scanner = {'session_date': '2026-07-04', 'top_signals': []}
    board = _build_board(now, empty_scanner)
    sync = select_synced_tradecard(board=board, now=now, legacy_ticker='CEATLTD')
    if sync.get('reference_best'):
        return _fail('empty board must not have reference_best')
    legacy_card = {
        'ok': True,
        'ticker': 'CEATLTD',
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
        text = format_tradecard_telegram(explain=False, freshness_meta={}, chat_id='weekend-empty')
    if 'CEATLTD' in text:
        return _fail('empty closed-market /tradecard must not show legacy CEATLTD')
    if 'NO CURRENT ENTRY' not in text.upper():
        return _fail('empty closed-market /tradecard must show NO CURRENT ENTRY')
    return 0


def test_build_label_51m() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51U':
        return _fail(f'expected AstraEdge 51U got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_closed_market_shows_reference_best_not_legacy,
        test_closed_market_empty_board_no_symbol,
        test_build_label_51m,
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
    print(f'ALL {len(tests)} TRADECARD_CLOSED_MARKET_4B12 TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
