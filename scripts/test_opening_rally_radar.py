#!/usr/bin/env python3
"""Phase 4B.0 — Opening Rally Radar + multi-candidate tradecard board."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IST = ZoneInfo('Asia/Kolkata')

RAILTEL_HEADLINE = (
    'RailTel received Rs 107.6 crore work order from Mahanadi Coalfields'
)


def _fail(msg: str) -> int:
    print(f'OPENING_RALLY_RADAR_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 7, 1, hour, minute, tzinfo=IST)


def _railtel_catalyst() -> dict:
    return {
        'priority_list': [{
            'ticker': 'RAILTEL',
            'headline': RAILTEL_HEADLINE,
            'catalyst_type': 'ORDER_WIN',
            'side': 'BULLISH',
            'score': 88,
            'freshness_label': 'today',
        }],
    }


def _scanner(*rows: dict) -> dict:
    return {'top_signals': list(rows)}


def _row(ticker: str, vol: float, chg: float = 1.2, **extra) -> dict:
    base = {
        'ticker': ticker,
        'volume_ratio': vol,
        'change_percent': chg,
        'price': 150.0,
        'open_price': 148.0,
        'vwap': 149.0,
        'direction': 'BULLISH',
    }
    base.update(extra)
    return base


def test_railtel_lifecycle() -> int:
    from backend.trading.opening_rally_radar import (
        build_opening_rally_board,
        pick_best_opening_tradecard,
    )

    catalyst = _railtel_catalyst()
    scanner_armed = _scanner(_row('RAILTEL', 1.1))
    scanner_ignition = _scanner(_row('RAILTEL', 3.8))
    scanner_confirm = _scanner(_row('RAILTEL', 3.8, chg=2.1))

    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=['railways_metro']):
        armed = build_opening_rally_board(
            now=_dt(8, 45),
            catalyst_payload=catalyst,
            scanner_payload=scanner_armed,
        )
        rail_armed = next((r for r in armed['ranked_candidates'] if r['ticker'] == 'RAILTEL'), None)
        if not rail_armed or rail_armed['state'] != 'RADAR_ARMED':
            return _fail(f'RAILTEL should be RADAR_ARMED at 08:45 got {rail_armed}')

        ignition = build_opening_rally_board(
            now=_dt(9, 20),
            catalyst_payload=catalyst,
            scanner_payload=scanner_ignition,
        )
        rail_ign = next((r for r in ignition['ranked_candidates'] if r['ticker'] == 'RAILTEL'), None)
        if not rail_ign or rail_ign['state'] != 'VOLUME_IGNITION':
            return _fail(f'RAILTEL should be VOLUME_IGNITION at 09:20 got {rail_ign}')

        confirm = build_opening_rally_board(
            now=_dt(9, 25),
            catalyst_payload=catalyst,
            scanner_payload=scanner_confirm,
        )
        rail_conf = next((r for r in confirm['ranked_candidates'] if r['ticker'] == 'RAILTEL'), None)
        if not rail_conf or rail_conf['state'] != 'TRADECARD_CANDIDATE':
            return _fail(f'RAILTEL should be TRADECARD_CANDIDATE at 09:25 got {rail_conf}')

        best, score, _ = pick_best_opening_tradecard(confirm)
        if best != 'RAILTEL':
            return _fail(f'pick_best should be RAILTEL got {best!r} score={score}')
    return 0


def test_rvnl_beats_tata_momentum_only() -> int:
    from backend.trading.opening_rally_radar import build_opening_rally_board

    catalyst = {
        'priority_list': [{
            'ticker': 'RVNL',
            'headline': 'RVNL bags railway order worth Rs 500 crore',
            'catalyst_type': 'ORDER_WIN',
            'side': 'BULLISH',
            'score': 80,
        }],
    }
    scanner = _scanner(
        _row('TATAMOTORS', 10.0, chg=2.5),
        _row('RVNL', 5.0, chg=2.0),
    )
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', side_effect=lambda s: ['railways_metro'] if s == 'RVNL' else []):
        board = build_opening_rally_board(
            now=_dt(9, 20),
            catalyst_payload=catalyst,
            scanner_payload=scanner,
        )
        ranked = board.get('ranked_candidates') or []
        if len(ranked) < 2:
            return _fail('expected both RVNL and TATA in radar')
        if ranked[0]['ticker'] != 'RVNL':
            return _fail(f'RVNL should rank above TATA got {ranked[0]["ticker"]}')
        tata = next((r for r in ranked if r['ticker'] == 'TATAMOTORS'), None)
        if not tata or tata['state'] != 'MOMENTUM_ONLY_WATCH':
            return _fail(f'TATA should be MOMENTUM_ONLY_WATCH got {tata}')
    return 0


def test_news_no_volume_armed_only() -> int:
    from backend.trading.opening_rally_radar import build_opening_rally_board

    catalyst = _railtel_catalyst()
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=['railways_metro']):
        board = build_opening_rally_board(
            now=_dt(9, 20),
            catalyst_payload=catalyst,
            scanner_payload=_scanner(),
        )
        row = next((r for r in board['ranked_candidates'] if r['ticker'] == 'RAILTEL'), None)
        if not row or row['state'] != 'RADAR_ARMED':
            return _fail(f'news-only RAILTEL should stay RADAR_ARMED got {row}')
    return 0


def test_volume_no_news_momentum_watch() -> int:
    from backend.trading.opening_rally_radar import build_opening_rally_board

    scanner = _scanner(_row('IDEA', 4.5, chg=1.8))
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]):
        board = build_opening_rally_board(
            now=_dt(9, 20),
            catalyst_payload={'priority_list': []},
            scanner_payload=scanner,
        )
        row = next((r for r in board['ranked_candidates'] if r['ticker'] == 'IDEA'), None)
        if not row or row['state'] != 'MOMENTUM_ONLY_WATCH':
            return _fail(f'volume-only IDEA should be MOMENTUM_ONLY_WATCH got {row}')
        if row['score'] > 65:
            return _fail(f'volume-only should have lower confidence score got {row["score"]}')
    return 0


def test_extended_chase_risk() -> int:
    from backend.trading.opening_rally_radar import build_opening_rally_board

    scanner = _scanner(_row('RVNL', 6.0, chg=5.5))
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]):
        board = build_opening_rally_board(
            now=_dt(9, 40),
            catalyst_payload={'priority_list': []},
            scanner_payload=scanner,
        )
        row = next((r for r in board['ranked_candidates'] if r['ticker'] == 'RVNL'), None)
        if not row or row['state'] != 'CHASE_RISK':
            return _fail(f'extended RVNL at 09:40 should be CHASE_RISK got {row}')
    return 0


def test_tradecards_command_multiple() -> int:
    from backend.telegram.lazy_command_runner import run_tradecards_only
    from backend.trading.opening_rally_radar import build_opening_rally_board

    fake_board = {
        'ranked_candidates': [
            {'ticker': 'RAILTEL', 'state': 'TRADECARD_CANDIDATE', 'score': 78, 'why': ['fresh order news']},
            {'ticker': 'RVNL', 'state': 'VOLUME_IGNITION', 'score': 72, 'why': ['volume 4x']},
        ],
    }
    with patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=fake_board), \
         patch('backend.trading.opening_rally_radar.pick_best_opening_tradecard', return_value=('RAILTEL', 78, ['RVNL'])):
        text = run_tradecards_only().get('text') or ''
    if 'TRADECARDS' not in text.upper():
        return _fail('/tradecards missing header')
    if text.count('<b>RAILTEL</b>') < 1 or text.count('<b>RVNL</b>') < 1:
        return _fail('/tradecards must list multiple candidates')
    return 0


def test_tradecard_returns_best_one() -> int:
    from backend.telegram.lazy_command_runner import run_tradecard_only
    from backend.telegram.response_format import format_tradecard_telegram

    fake_card = {
        'ok': True,
        'ticker': 'RAILTEL',
        'status': 'VALID_ENTRY',
        'current_price': 150,
        'entry_zone': '149–151',
        'stop_loss': 147,
        'target_1': 153,
        'target_2': 156,
        'risk_reward': 2.0,
        'capital_plan': 'Paper only',
        'reason': 'Opening rally candidate',
        'invalid_if': 'Below 147',
        'confidence': 'MEDIUM',
        'paper_only': True,
    }
    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value={}):
        text = format_tradecard_telegram(explain=False)
        result = run_tradecard_only('')
    body = result.get('text') or text
    if 'TRADE CARD' not in body.upper():
        return _fail('/tradecard must return single trade card')
    if body.count('<b>RAILTEL</b>') != 1 and 'RAILTEL' not in body:
        return _fail('/tradecard should show one ticker')
    if 'TRADECARDS' in body.upper():
        return _fail('/tradecard must not be multi-board output')
    return 0


def test_news_scoring_confirm() -> int:
    from backend.trading.tradecard_evidence import build_tradecard_evidence_matrix

    context = {
        'news': {
            'priority_list': [{
                'ticker': 'RAILTEL',
                'headline': RAILTEL_HEADLINE,
                'catalyst_type': 'ORDER_WIN',
                'side': 'BULLISH',
            }],
        },
        'scanner': {
            'top_signals': [_row('RAILTEL', 3.8)],
        },
    }
    matrix = build_tradecard_evidence_matrix('RAILTEL', context=context)
    news_items = [i for i in (matrix.get('evidence_items') or []) if i.get('module') == 'news']
    if not news_items:
        return _fail('news evidence item missing')
    if news_items[0].get('verdict') != 'confirm':
        return _fail(f'company order news must be confirm not {news_items[0].get("verdict")}')
    directs = matrix.get('direct_confirms') or []
    modules = {d.get('module') for d in directs}
    if 'news' not in modules or 'scanner' not in modules:
        return _fail(f'direct confirms should include scanner+news got {modules}')
    return 0


def test_existing_tradecard_tests() -> int:
    import subprocess

    scripts = [
        'scripts/test_trade_card_telegram_command.py',
        'scripts/test_today_tradecard_same_priority_engine.py',
    ]
    for rel in scripts:
        proc = subprocess.run([sys.executable, str(PROJECT_ROOT / rel)], capture_output=True, text=True)
        if proc.returncode != 0:
            return _fail(f'{rel} failed: {proc.stderr or proc.stdout}')
    return 0


def main() -> int:
    steps = [
        test_railtel_lifecycle,
        test_rvnl_beats_tata_momentum_only,
        test_news_no_volume_armed_only,
        test_volume_no_news_momentum_watch,
        test_extended_chase_risk,
        test_tradecards_command_multiple,
        test_tradecard_returns_best_one,
        test_news_scoring_confirm,
        test_existing_tradecard_tests,
    ]
    for step in steps:
        rc = step()
        if rc:
            return rc
    print('OPENING_RALLY_RADAR_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
