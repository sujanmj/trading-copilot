#!/usr/bin/env python3
"""Phase 4B.7 — All-cap gainers discovery + opening radar merge (AstraEdge 51H)."""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
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
REDIRECT = 'Use /radar for opening rally candidates.'


def _fail(msg: str) -> int:
    print(f'ALL_CAP_GAINERS_4B7_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 7, 1, hour, minute, tzinfo=IST)


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


def test_gainers_command() -> int:
    from backend.telegram.telegram_analysis_bot import handle_analysis_command, parse_command
    from backend.telegram.telegram_command_normalize import normalize_parsed_command

    cmd, _ = normalize_parsed_command(*parse_command('/gainers'))
    if cmd != 'gainers':
        return _fail(f'/gainers must parse to gainers got {cmd!r}')

    gainers_text = (
        '<b>ALL-CAP GAINERS — live discovery</b>\n'
        '<b>Large cap:</b>\n1. <b>COFORGE</b>'
    )
    with patch('backend.telegram.lazy_command_runner.run_gainers_only', return_value={'text': gainers_text}) as mock:
        results = handle_analysis_command('/gainers', 'test', dry_run=True)
        mock.assert_called_once()
    if 'ALL-CAP GAINERS' not in str(results[0].get('text', '')):
        return _fail('/gainers must return all-cap gainers board')
    return 0


def test_help_and_schedule() -> int:
    from backend.telegram.premarket_scheduler import format_schedule_text
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command

    help_results = handle_analysis_command('/help', 'test', dry_run=True)
    help_text = str(help_results[0].get('text', ''))
    if help_text != HELP_TEXT:
        return _fail('/help must return HELP_TEXT')
    if '/gainers' not in help_text:
        return _fail('/help must include /gainers')
    if '/opening' in help_text.lower():
        return _fail('/help must not include /opening')

    schedule_results = handle_analysis_command('/schedule', 'test', dry_run=True)
    schedule_text = str(schedule_results[0].get('text', ''))
    if schedule_text != format_schedule_text():
        return _fail('/schedule must return format_schedule_text()')
    if '/gainers' not in schedule_text:
        return _fail('/schedule must include /gainers')
    if '/opening' in schedule_text.lower():
        return _fail('/schedule must not include /opening')
    return 0


def test_bucket_render() -> int:
    from backend.telegram.response_format import format_all_cap_gainers_telegram
    from backend.trading.all_cap_gainers import scan_all_cap_gainers

    live_now = datetime(2026, 5, 27, 10, 30, tzinfo=IST)
    scanner = _scanner(
        _row('COFORGE', 4.2, 1.2, price=5200),
        _row('SONACOMS', 5.5, 0.9, price=650),
        _row('SMALLCAPX', 6.0, 0.8, price=120),
        _row('VISL', 8.0, 0.5, price=80),
    )
    scanner['session_date'] = '2026-05-27'
    scan = scan_all_cap_gainers(scanner_payload=scanner, now=live_now)
    text = format_all_cap_gainers_telegram(gainer_scan=scan)
    for label in ('Large cap', 'Mid cap', 'Small cap', 'New listings / demerged'):
        if label not in text:
            return _fail(f'/gainers output must render {label!r} bucket section')
    return 0


def test_it_gainers_no_railways_theme_contamination() -> int:
    """IT all-cap gainers must not inherit railways theme from a shared mock list."""
    from backend.trading.opening_rally_radar import build_opening_rally_board

    catalyst = {
        'priority_list': [{
            'ticker': 'INFY',
            'headline': 'Infosys result alert beats estimates',
            'catalyst_type': 'RESULT_ALERT',
            'side': 'BULLISH',
            'score': 86,
        }],
    }
    scanner = _scanner(
        _row('INFY', 4.1, 1.0, price=1540.0, open_price=1480.0, vwap=1500.0),
        _row('HCLTECH', 3.2, 1.0, price=1020.0, open_price=990.0, vwap=1000.0),
        _row('TCS', 2.2, 1.0, price=3900.0, open_price=3820.0, vwap=3850.0),
        _row('RAILTEL', 2.5, 1.2, price=320.0, open_price=310.0, vwap=315.0),
    )
    shared_themes = ['railways_metro']
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=shared_themes):
        board = build_opening_rally_board(
            now=_dt(9, 20),
            catalyst_payload=catalyst,
            scanner_payload=scanner,
        )

    by_ticker = {str(r.get('ticker')): r for r in board.get('ranked_candidates') or []}
    for sym in ('INFY', 'TCS', 'HCLTECH'):
        row = by_ticker.get(sym)
        if not row:
            return _fail(f'{sym} must appear on opening board')
        why = ' + '.join(row.get('why') or []).lower()
        if 'railways metro theme' in why:
            return _fail(f'{sym} must not inherit railways metro theme: {why!r}')
        if 'it sector breadth confirmation' not in why:
            return _fail(f'{sym} must include IT sector breadth confirmation: {why!r}')

    infy = by_ticker['INFY']
    infy_why = ' + '.join(infy.get('why') or []).lower()
    if 'fresh result alert' not in infy_why:
        return _fail(f'INFY must include fresh result alert: {infy_why!r}')

    railtel = by_ticker.get('RAILTEL')
    if not railtel:
        return _fail('RAILTEL must appear on opening board')
    rail_why = ' + '.join(railtel.get('why') or []).lower()
    if 'railways metro theme' not in rail_why:
        return _fail(f'RAILTEL must keep railways metro theme: {rail_why!r}')
    return 0


def test_sonacom_coforge_promotion() -> int:
    from backend.trading.all_cap_gainers import scan_all_cap_gainers
    from backend.trading.opening_rally_radar import build_opening_rally_board, pick_best_opening_tradecard

    scanner = _scanner(
        _row('SONACOMS', 5.2, 0.85, price=650),
        _row('COFORGE', 4.5, 1.1, price=5200),
        _row('PERSISTENT', 3.8, 1.0, price=4800),
    )
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]):
        board = build_opening_rally_board(
            now=_dt(9, 20),
            catalyst_payload={},
            scanner_payload=scanner,
        )
    promoted = (board.get('gainer_scan') or {}).get('promoted') or []
    for sym in ('SONACOMS', 'COFORGE', 'PERSISTENT'):
        if sym not in promoted:
            return _fail(f'{sym} should be promoted to radar')
    ranked = {r['ticker']: r for r in board.get('ranked_candidates') or []}
    coforge = ranked.get('COFORGE')
    if not coforge or not coforge.get('gainer_promoted'):
        return _fail('COFORGE should have gainer_promoted on radar board')
    if coforge.get('state') not in ('TOP_GAINER_CONFIRM', 'PRICE_IGNITION', 'PULLBACK_ONLY_PLAN'):
        return _fail(f'COFORGE unexpected state {coforge.get("state")!r}')
    return 0


def test_new_listing_demerger_risk_labels() -> int:
    from backend.telegram.response_format import format_tradecards_telegram
    from backend.trading.opening_rally_radar import build_opening_rally_board

    scanner = _scanner(
        _row('VISL', 7.5, 0.45, price=75),
        _row('VOGL', 6.8, 0.42, price=90),
        _row('VEDPOWER', 9.0, 0.38, price=110),
    )
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]):
        board = build_opening_rally_board(
            now=_dt(9, 20),
            catalyst_payload={},
            scanner_payload=scanner,
        )
    scan = __import__('backend.trading.all_cap_gainers', fromlist=['scan_all_cap_gainers']).scan_all_cap_gainers(
        scanner_payload=scanner,
        now=_dt(9, 20),
    )
    visl_meta = (scan.get('by_symbol') or {}).get('VISL') or {}
    if not visl_meta.get('new_listing'):
        return _fail('VISL should be flagged new_listing')
    vogl_meta = (scan.get('by_symbol') or {}).get('VOGL') or {}
    if not vogl_meta.get('demerger'):
        return _fail('VOGL should be flagged demerger')

    ranked = {r['ticker']: r for r in board.get('ranked_candidates') or []}
    visl = ranked.get('VISL')
    if visl and visl.get('volume_ratio', 0) >= 0.35:
        if visl.get('state') not in ('NEW_LISTING_MOMENTUM', 'DEMERGER_MOMENTUM'):
            return _fail(
                f'VISL with volume should be NEW_LISTING or DEMERGER momentum got {visl.get("state")!r}'
            )

    text = format_tradecards_telegram(board=board)
    if 'VISL' in text or 'VOGL' in text or 'VEDPOWER' in text:
        if 'Risk:' not in text:
            return _fail('tradecards must show risk lines for new listing/demerger rows')
    return 0


def test_circuit_not_blind_tradecard() -> int:
    from backend.trading.opening_rally_radar import build_opening_rally_board, pick_best_opening_tradecard

    scanner = _scanner(
        _row('PUMPXYZ', 9.8, 0.1, price=25, volume=10000),
        _row('COFORGE', 4.0, 1.2, price=5200),
    )
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]):
        board = build_opening_rally_board(
            now=_dt(9, 25),
            catalyst_payload={},
            scanner_payload=scanner,
        )
    best, _, _ = pick_best_opening_tradecard(board)
    if best == 'PUMPXYZ':
        return _fail('pure circuit/low-liquidity must not be blind best tradecard')
    if best != 'COFORGE':
        return _fail(f'COFORGE should beat circuit pump got best={best!r}')
    return 0


def test_gainer_only_not_blind_tradecard() -> int:
    from backend.trading.opening_rally_radar import build_opening_rally_board, pick_best_opening_tradecard

    scanner = _scanner(
        _row('SONACOMS', 3.5, 0.25, price=650),
        _row('COFORGE', 4.2, 1.1, price=5200),
    )
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]):
        board = build_opening_rally_board(
            now=_dt(9, 25),
            catalyst_payload={},
            scanner_payload=scanner,
        )
    ranked = {r['ticker']: r for r in board.get('ranked_candidates') or []}
    sona = ranked.get('SONACOMS')
    if sona and sona.get('gainer_promoted') and sona.get('state') == 'PRICE_IGNITION':
        best, _, _ = pick_best_opening_tradecard(board)
        if best == 'SONACOMS':
            return _fail('gainer-only without confirmation must not be blind best tradecard')
    return 0


def test_radar_merges_gainers() -> int:
    from backend.telegram.response_format import format_opening_radar_telegram
    from backend.trading.opening_rally_radar import build_opening_rally_board

    scanner = _scanner(_row('COFORGE', 4.5, 1.0, price=5200))
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]):
        board = build_opening_rally_board(
            now=_dt(9, 20),
            catalyst_payload={},
            scanner_payload=scanner,
        )
    text = format_opening_radar_telegram(board=board)
    if 'Promoted to /radar' not in text and 'COFORGE' not in text:
        return _fail('/radar must merge top gainers onto board')
    return 0


def test_tradecards_ranks_all_cap() -> int:
    from backend.telegram.response_format import format_tradecards_telegram
    from backend.trading.opening_rally_radar import build_opening_rally_board, pick_best_opening_tradecard

    scanner = _scanner(
        _row('COFORGE', 4.5, 1.1, price=5200),
        _row('SONACOMS', 5.0, 0.9, price=650),
    )
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]):
        board = build_opening_rally_board(
            now=_dt(9, 25),
            catalyst_payload={},
            scanner_payload=scanner,
        )
    text = format_tradecards_telegram(board=board)
    if 'TRADECARDS' not in text:
        return _fail('/tradecards must render tradecards board')
    best, score, _ = pick_best_opening_tradecard(board)
    if not best or score <= 0:
        return _fail('/tradecards board must have eligible best pick')
    if 'Best pick' not in text:
        return _fail('/tradecards must show best pick line')
    return 0


def test_opening_redirects_to_radar() -> int:
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    with patch('backend.telegram.lazy_command_runner.run_radar_only') as mock_radar:
        results = handle_analysis_command('/opening', 'test', dry_run=True)
        mock_radar.assert_not_called()
    if REDIRECT not in str(results[0].get('text', '')):
        return _fail('/opening must redirect to /radar')
    return 0


def test_extended_uses_gainer_meta() -> int:
    from backend.trading.all_cap_gainers import apply_gainer_context_to_candidate

    row = {
        'ticker': 'COFORGE',
        'score': 50,
        'state': 'RADAR_ARMED',
        'why': [],
        'change_percent': 7.0,
        'volume_ratio': 0.5,
        'extended': False,
    }
    gainer_meta = {
        'bucket': 'large cap',
        'rank_in_bucket': 2,
        'extended': True,
        'risk_blocked': False,
        'why': ['top large cap gainer'],
    }
    out = apply_gainer_context_to_candidate(
        row,
        gainer_meta,
        scanner_row=row,
        has_catalyst=False,
        sector_breadth=False,
        previous_mover=False,
    )
    if out.get('state') != 'PULLBACK_ONLY_PLAN':
        return _fail('gainer_meta.extended must trigger PULLBACK_ONLY_PLAN when row.extended is false')

    row2 = dict(row)
    row2['extended'] = True
    gainer_meta2 = dict(gainer_meta)
    gainer_meta2['extended'] = False
    out2 = apply_gainer_context_to_candidate(
        row2,
        gainer_meta2,
        scanner_row=row2,
        has_catalyst=False,
        sector_breadth=False,
        previous_mover=False,
    )
    if out2.get('state') != 'PULLBACK_ONLY_PLAN':
        return _fail('row.extended must trigger PULLBACK_ONLY_PLAN when gainer_meta.extended is false')
    return 0


def test_gainer_scan_logging() -> int:
    from backend.trading.opening_rally_radar import build_opening_rally_board

    scanner = _scanner(_row('COFORGE', 4.5, 1.0, price=5200))
    buf = io.StringIO()
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
         redirect_stdout(buf):
        build_opening_rally_board(
            now=_dt(9, 20),
            catalyst_payload={},
            scanner_payload=scanner,
        )
    logs = buf.getvalue()
    if '[GAINER_PROMOTED_TO_RADAR]' not in logs:
        return _fail('opening board must log gainer_scan promotions')
    return 0


def test_format_opening_radar_action_gainer_states() -> int:
    from backend.trading.opening_rally_radar import format_opening_radar_action

    for state, needle in (
        ('TOP_GAINER_CONFIRM', 'top gainer'),
        ('NEW_LISTING_MOMENTUM', 'new listing'),
        ('DEMERGER_MOMENTUM', 'demerger'),
    ):
        action = format_opening_radar_action(state)
        if needle not in action.lower():
            return _fail(f'format_opening_radar_action({state!r}) missing {needle!r}')
    return 0


def main() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
    from backend.trading.all_cap_gainers import STAGE as GAINER_STAGE
    from backend.trading.opening_rally_radar import STAGE as RADAR_STAGE

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51L':
        return _fail(f'expected AstraEdge 51L got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    if GAINER_STAGE != '4B.11' or RADAR_STAGE != '4B.11':
        return _fail(f'expected stage 4B.11 got gainer={GAINER_STAGE!r} radar={RADAR_STAGE!r}')

    tests = (
        test_gainers_command,
        test_help_and_schedule,
        test_bucket_render,
        test_it_gainers_no_railways_theme_contamination,
        test_sonacom_coforge_promotion,
        test_new_listing_demerger_risk_labels,
        test_circuit_not_blind_tradecard,
        test_gainer_only_not_blind_tradecard,
        test_radar_merges_gainers,
        test_tradecards_ranks_all_cap,
        test_opening_redirects_to_radar,
        test_extended_uses_gainer_meta,
        test_gainer_scan_logging,
        test_format_opening_radar_action_gainer_states,
    )
    for test_fn in tests:
        rc = test_fn()
        if rc:
            return rc

    print('ALL_CAP_GAINERS_4B7_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
