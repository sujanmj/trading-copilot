#!/usr/bin/env python3
"""Phase 4B.12 — cap bucket visibility on /tradecards, /tradecard, and /radar."""

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
    print(f'CAP_BUCKET_VISIBILITY_4B12_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(hour: int, minute: int, *, day: int = 1) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=IST)


def _weekend_dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 7, 4, hour, minute, tzinfo=IST)


def _scanner(*rows: dict) -> dict:
    return {
        'session_date': '2026-07-01',
        'top_signals': list(rows),
    }


def _row(ticker: str, chg: float, vol: float = 1.0, **extra) -> dict:
    base = {
        'ticker': ticker,
        'change_percent': chg,
        'volume_ratio': vol,
        'price': 500.0,
        'open_price': 480.0,
        'vwap': 490.0,
        'direction': 'BULLISH',
        'volume': 200000,
    }
    base.update(extra)
    return base


def _build_board(now: datetime, scanner: dict, *, live: bool = False) -> dict:
    from backend.trading.opening_rally_radar import build_opening_rally_board

    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
         patch('backend.trading.opening_rally_radar._load_json', return_value={}):
        board = build_opening_rally_board(
            now=now,
            catalyst_payload={},
            scanner_payload=scanner,
            premarket_payload={},
        )
    if live:
        from scripts.test_board_fixtures import apply_live_board_overlay

        return apply_live_board_overlay(board)
    return board


def test_tradecards_show_cap_bucket_inline() -> int:
    from backend.telegram.response_format import format_tradecards_telegram

    scanner = _scanner(
        _row('PERSISTENT', 3.8, 1.0, price=4800),
        _row('SONACOMS', 5.0, 0.9, price=650),
        _row('COFORGE', 4.5, 1.1, price=5200),
    )
    board = _build_board(_dt(9, 25), scanner, live=True)
    text = format_tradecards_telegram(board=board)
    if 'TOP CANDIDATES' not in text:
        return _fail('/tradecards must show live TOP CANDIDATES header')
    if 'Large cap' not in text and 'Mid cap' not in text:
        return _fail('/tradecards must show cap bucket inline for ranked candidates')
    if 'PERSISTENT' in text and '— Large cap —' not in text and '— Mid cap —' not in text:
        return _fail('PERSISTENT line must include cap bucket between symbol and state')
    bucket_headers = [line for line in text.splitlines() if line.strip().startswith('<b>Large cap')]
    if bucket_headers:
        return _fail('/tradecards must not group by bucket headers')
    return 0


def test_tradecard_shows_cap_bucket_header() -> int:
    from backend.telegram.response_format import format_tradecard_telegram

    board = _build_board(
        _dt(9, 25),
        _scanner(_row('PERSISTENT', 3.8, 1.0, price=4800), _row('COFORGE', 4.2, 1.1, price=5200)),
        live=True,
    )
    sync = {
        'selected': 'PERSISTENT',
        'board': board,
        'reference_only': False,
        'session_stale': False,
    }
    card = {
        'ok': True,
        'ticker': 'PERSISTENT',
        'status': 'NO_ACTIVE_ENTRY',
        'entry_zone': 'NO ACTIVE ENTRY',
        'reason': 'aligned with /tradecards best pick',
        'current_price': 4800,
        'stop_loss': 4700,
        'target_1': 4900,
        'target_2': 5000,
        'risk_reward': 1.5,
        'confidence': 'MEDIUM',
        'capital_plan': 'Paper only',
        '_opening_radar_context': {
            'ticker': 'PERSISTENT',
            'gainer_bucket': 'large cap',
            'gainer_promoted': True,
            'from_board': True,
            'why': ['top large cap gainer'],
            'state': 'TOP_GAINER_CONFIRM',
        },
    }
    with patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value=sync), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=card), \
         patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False), \
         patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value={}), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''):
        text = format_tradecard_telegram(explain=False, freshness_meta={}, chat_id='cap-bucket-live')
    if 'Cap bucket: Large cap' not in text:
        return _fail('/tradecard must show Cap bucket header near top')
    return 0


def test_radar_shows_cap_bucket_inline() -> int:
    from backend.telegram.response_format import format_opening_radar_telegram

    board = _build_board(_dt(9, 20), _scanner(_row('COFORGE', 4.5, 1.0, price=5200)), live=True)
    text = format_opening_radar_telegram(board=board)
    if 'COFORGE' not in text:
        return _fail('/radar must list COFORGE')
    if '— Large cap —' not in text and '— Mid cap —' not in text:
        return _fail('/radar candidate lines must include cap bucket inline')
    return 0


def test_unknown_cap_bucket_no_crash() -> int:
    from backend.telegram.response_format import format_tradecards_telegram
    from backend.trading.all_cap_gainers import format_cap_bucket_header, format_cap_bucket_inline
    from scripts.test_board_fixtures import apply_live_board_overlay, quality_ranked_candidate

    board = apply_live_board_overlay({
        'ranked_candidates': [
            quality_ranked_candidate(
                ticker='MYSTERY',
                score=62,
                state='RADAR_ARMED',
                why=['theme watch'],
            ),
        ],
        'time_ist': '09:20',
        'phase': 'OPEN',
        'session_date': '2026-07-01',
    })
    with patch('backend.trading.all_cap_gainers._screener_cap_bucket_exact', return_value=''), \
         patch('backend.telegram.response_format._persist_tradecards_decision_memory'):
        text = format_tradecards_telegram(board=board)
    if 'Unknown cap' not in text:
        return _fail('missing gainer_bucket must render Unknown cap inline')
    if format_cap_bucket_inline({'ticker': 'MYSTERY'}) != 'Unknown cap':
        return _fail('format_cap_bucket_inline without bucket must return Unknown cap')
    if format_cap_bucket_header({'ticker': 'MYSTERY'}) != 'Cap bucket: Unknown':
        return _fail('format_cap_bucket_header without bucket must return Cap bucket: Unknown')
    return 0


def test_mixed_top10_not_grouped() -> int:
    from backend.telegram.response_format import format_tradecards_telegram

    scanner = _scanner(
        _row('PERSISTENT', 3.8, 1.0, price=4800),
        _row('SONACOMS', 5.0, 0.9, price=650),
        _row('COFORGE', 4.5, 1.1, price=5200),
    )
    board = _build_board(_dt(9, 25), scanner, live=True)
    text = format_tradecards_telegram(board=board)
    lines = [ln for ln in text.splitlines() if ln.strip()[:1].isdigit() and '. <b>' in ln]
    if len(lines) < 2:
        return _fail('expected multiple ranked candidate lines')
    caps_seen = set()
    for line in lines:
        for cap in ('Large cap', 'Mid cap', 'Small cap', 'Unknown cap'):
            if f'— {cap} —' in line:
                caps_seen.add(cap)
    if len(caps_seen) < 1:
        return _fail('mixed list should show at least one cap bucket label')
    grouped = any(
        ln.strip().startswith('<b>') and 'cap:</b>' in ln.lower()
        for ln in text.splitlines()
    )
    if grouped:
        return _fail('mixed top-10 must not use bucket section headers')
    return 0


def test_ranking_unchanged() -> int:
    from backend.trading.opening_rally_radar import build_opening_rally_board, pick_best_opening_tradecard
    from scripts.test_board_fixtures import apply_live_board_overlay

    scanner = _scanner(
        _row('COFORGE', 4.5, 1.1, price=5200),
        _row('SONACOMS', 5.0, 0.9, price=650),
    )
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
         patch('backend.trading.opening_rally_radar._load_json', return_value={}):
        board = apply_live_board_overlay(
            build_opening_rally_board(now=_dt(9, 25), catalyst_payload={}, scanner_payload=scanner),
        )
    best, score, _ = pick_best_opening_tradecard(board)
    ranked = [r.get('ticker') for r in board.get('ranked_candidates') or [] if r.get('state') != 'REJECTED']
    if not best or score <= 0:
        return _fail('board must still pick a best tradecard')
    if ranked and ranked[0] != best:
        return _fail(f'top ranked candidate {ranked[0]!r} must match best pick {best!r}')
    return 0


def test_closed_market_reference_unchanged() -> int:
    from backend.telegram.response_format import format_tradecard_telegram, format_tradecards_telegram
    from backend.trading.opening_rally_radar import select_synced_tradecard

    now = _weekend_dt(2, 5)
    scanner = {'session_date': '2026-07-04', 'top_signals': [_row('PERSISTENT', 3.5, 1.2, price=4800)]}
    board = _build_board(now, scanner)
    tradecards_text = format_tradecards_telegram(board=board)
    if 'PREVIOUS-SESSION REFERENCE' not in tradecards_text:
        return _fail('weekend /tradecards must stay previous-session reference')
    if 'TOP CANDIDATES' in tradecards_text:
        return _fail('weekend /tradecards must not show TOP CANDIDATES')

    sync = select_synced_tradecard(board=board, now=now, legacy_ticker='CEATLTD')
    legacy_card = {'ok': True, 'ticker': 'CEATLTD', 'status': 'NO_ACTIVE_ENTRY', 'reason': 'legacy'}
    with patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value=sync), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=legacy_card), \
         patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False), \
         patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value={}), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''):
        tradecard_text = format_tradecard_telegram(explain=False, freshness_meta={}, chat_id='weekend-cap')
    if 'CEATLTD' in tradecard_text:
        return _fail('closed-market /tradecard must not show legacy ticker')
    if 'PREVIOUS-SESSION REFERENCE' not in tradecard_text:
        return _fail('closed-market /tradecard must stay previous-session reference')
    if 'Cap bucket:' not in tradecard_text:
        return _fail('closed-market /tradecard should still show cap bucket line')
    return 0


def test_evidence_matrix_cap_metadata() -> int:
    from backend.trading.tradecard_evidence import build_tradecard_evidence_matrix

    matrix = build_tradecard_evidence_matrix(
        'PERSISTENT',
        context={
            'opening_radar': {
                'ticker': 'PERSISTENT',
                'gainer_bucket': 'large cap',
                'gainer_promoted': True,
                'from_board': True,
                'why': ['top large cap gainer'],
                'state': 'TOP_GAINER_CONFIRM',
                'board_row': {'gainer_bucket': 'large cap', 'volume_ratio': 1.1},
            },
        },
    )
    if not matrix:
        return _fail('evidence matrix must build')
    if matrix.get('cap_bucket') != 'cap_bucket=large cap':
        return _fail(f'expected cap_bucket metadata got {matrix.get("cap_bucket")!r}')
    from backend.trading.tradecard_evidence import format_tradecard_evidence_matrix_telegram

    compact = format_tradecard_evidence_matrix_telegram(matrix, compact=True)
    if 'Metadata: cap_bucket=large cap' not in compact:
        return _fail('compact evidence matrix must show Metadata cap_bucket line')
    return 0


def test_build_label_51m() -> int:
    from scripts.test_build_helpers import assert_canonical_build

    err = assert_canonical_build(_fail)
    if err:
        return err
    return 0


def main() -> int:
    tests = (
        test_tradecards_show_cap_bucket_inline,
        test_tradecard_shows_cap_bucket_header,
        test_radar_shows_cap_bucket_inline,
        test_unknown_cap_bucket_no_crash,
        test_mixed_top10_not_grouped,
        test_ranking_unchanged,
        test_closed_market_reference_unchanged,
        test_evidence_matrix_cap_metadata,
        test_build_label_51m,
    )
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
    print(f'ALL {len(tests)} CAP_BUCKET_VISIBILITY_4B12 TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
