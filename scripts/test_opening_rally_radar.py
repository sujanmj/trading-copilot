#!/usr/bin/env python3
"""Phase 4B.0 — Opening Rally Radar + multi-candidate tradecard board."""

from __future__ import annotations

import sys
import tempfile
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
        if not rail_conf or rail_conf['state'] not in ('TRADECARD_CANDIDATE', 'TOP_GAINER_CONFIRM'):
            return _fail(f'RAILTEL should be tradecard-ready at 09:25 got {rail_conf}')

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
        if not tata or tata['state'] not in ('MOMENTUM_ONLY_WATCH', 'TOP_GAINER_CONFIRM'):
            return _fail(f'TATA should be momentum/gainer watch got {tata}')
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
        if not row or row['state'] not in ('CHASE_RISK', 'PULLBACK_ONLY_PLAN'):
            return _fail(f'extended RVNL at 09:40 should be chase/pullback risk got {row}')
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

    fake_board = {
        'ranked_candidates': [
            {'ticker': 'RAILTEL', 'state': 'TRADECARD_CANDIDATE', 'score': 78, 'why': ['fresh order news']},
        ],
        'phase': 'CONFIRMATION',
        'time_ist': '09:25',
    }
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
    with patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=fake_board), \
         patch('backend.trading.opening_rally_radar.pick_best_opening_tradecard', return_value=('RAILTEL', 78, [])), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card), \
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


def test_tradecard_selector_sync_with_tradecards() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.opening_rally_radar import select_synced_tradecard

    fake_board = {
        'ranked_candidates': [
            {'ticker': 'INFY', 'state': 'TRADECARD_CANDIDATE', 'score': 85, 'why': ['fresh news']},
            {'ticker': 'MAPMYINDIA', 'state': 'VOLUME_IGNITION', 'score': 70, 'why': ['volume']},
        ],
        'phase': 'CONFIRMATION',
        'time_ist': '09:25',
    }
    legacy_card = {
        'ok': True,
        'ticker': 'MAPMYINDIA',
        'status': 'VALID_ENTRY',
        'current_price': 150,
        'entry_zone': '149–151',
        'stop_loss': 147,
        'target_1': 153,
        'target_2': 156,
        'risk_reward': 2.0,
        'capital_plan': 'Paper only',
        'reason': 'legacy pick',
        'invalid_if': 'Below 147',
        'confidence': 'MEDIUM',
        'paper_only': True,
    }
    infy_card = {**legacy_card, 'ticker': 'INFY', 'reason': 'Opening rally candidate'}
    with patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=fake_board), \
         patch('backend.trading.opening_rally_radar.pick_best_opening_tradecard', return_value=('INFY', 85, ['MAPMYINDIA'])), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=legacy_card), \
         patch('backend.trading.trade_card_engine.build_trade_card', return_value=infy_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value={}):
        sync = select_synced_tradecard(legacy_ticker='MAPMYINDIA')
        if sync.get('tradecards_best') != 'INFY' or sync.get('selected') != 'INFY':
            return _fail(f'selector sync expected INFY got {sync}')
        text = format_tradecard_telegram(explain=False)
    if 'INFY' not in text:
        return _fail('/tradecard must select same top as /tradecards (INFY)')
    return 0


def test_chase_risk_after_0940_no_active_entry() -> int:
    from datetime import datetime
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.opening_rally_radar import select_synced_tradecard

    fake_board = {
        'ranked_candidates': [
            {'ticker': 'RVNL', 'state': 'CHASE_RISK', 'score': 60, 'why': ['extended']},
        ],
        'phase': 'CHASE',
        'time_ist': '09:42',
    }
    card = {
        'ok': True,
        'ticker': 'RVNL',
        'status': 'VALID_ENTRY',
        'current_price': 200,
        'entry_zone': '198–202',
        'stop_loss': 195,
        'target_1': 205,
        'target_2': 210,
        'risk_reward': 1.8,
        'capital_plan': 'Paper only',
        'reason': 'extended move',
        'invalid_if': 'Below 195',
        'confidence': 'LOW',
        'paper_only': True,
    }
    now = datetime(2026, 7, 1, 9, 42, tzinfo=IST)
    with patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=fake_board), \
         patch('backend.trading.opening_rally_radar.pick_best_opening_tradecard', return_value=('RVNL', 60, [])), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value={}):
        sync = select_synced_tradecard(legacy_ticker='RVNL', now=now)
        if sync.get('status_override') != 'NO_ACTIVE_ENTRY':
            return _fail(f'CHASE_RISK after 09:40 must override status got {sync}')
        text = format_tradecard_telegram(explain=False)
    if 'NO ACTIVE ENTRY' not in text.upper():
        return _fail('/tradecard must show NO ACTIVE ENTRY for CHASE_RISK after 09:40')
    return 0


def test_scheduled_opening_radar_candidates() -> int:
    from io import StringIO
    from contextlib import redirect_stdout
    from backend.trading.opening_rally_radar import run_scheduled_opening_radar_alert

    fake_board = {
        'ranked_candidates': [
            {'ticker': 'RAILTEL', 'state': 'VOLUME_IGNITION', 'score': 78, 'why': ['volume']},
        ],
        'phase': 'IGNITION',
        'time_ist': '09:20',
    }
    sent_messages: list[str] = []

    def _send(text: str) -> bool:
        sent_messages.append(text)
        return True

    with patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=fake_board), \
         patch('backend.orchestration.alert_quality_engine.evaluate_text_alert', return_value={'send': True}), \
         patch('backend.orchestration.alert_quality_engine.record_text_alert_sent'):
        buf = StringIO()
        with redirect_stdout(buf):
            ok = run_scheduled_opening_radar_alert(now=_dt(9, 20), send_fn=_send)
    if not ok or not sent_messages:
        return _fail('scheduled opening radar must send when candidates exist')
    if 'Opening Rally Radar' not in sent_messages[0]:
        return _fail('scheduled alert must use Opening Rally Radar title')
    if '[OPENING_RADAR_SCHEDULED]' not in buf.getvalue() or 'sent=yes' not in buf.getvalue():
        return _fail('scheduled run must log OPENING_RADAR_SCHEDULED sent=yes')
    return 0


def test_scheduled_opening_radar_no_candidate_silent() -> int:
    from io import StringIO
    from contextlib import redirect_stdout
    from backend.trading.opening_rally_radar import run_scheduled_opening_radar_alert

    fake_board = {'ranked_candidates': [], 'phase': 'IGNITION', 'time_ist': '09:20'}
    sent_messages: list[str] = []

    def _send(text: str) -> bool:
        sent_messages.append(text)
        return True

    with patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=fake_board):
        buf = StringIO()
        with redirect_stdout(buf):
            ok = run_scheduled_opening_radar_alert(now=_dt(9, 20), send_fn=_send)
    if ok or sent_messages:
        return _fail('no-candidate scheduled run must not send Telegram spam')
    logs = buf.getvalue()
    if '[OPENING_RADAR_NO_CANDIDATES]' not in logs or 'sent=no' not in logs:
        return _fail('no-candidate run must log OPENING_RADAR_NO_CANDIDATES and sent=no')
    return 0


def test_no_0910_scheduled_alert() -> int:
    from backend.telegram.premarket_scheduler import OPENING_MORNING_SLOTS, PREMARKET_SLOTS

    all_times = set(PREMARKET_SLOTS.values()) | set(OPENING_MORNING_SLOTS.values())
    if (9, 10) in all_times:
        return _fail('09:10 scheduled alert must not exist')
    sched_src = (PROJECT_ROOT / 'backend/telegram/premarket_scheduler.py').read_text(encoding='utf-8')
    if 'preopen_watch' in sched_src and "(9, 10)" in sched_src:
        return _fail('premarket_scheduler must not register 09:10 preopen_watch')
    return 0


def test_schedule_shows_four_morning_alerts() -> int:
    from backend.telegram.premarket_scheduler import format_schedule_text

    text = format_schedule_text()
    for label in (
        'Background prep',
        'Runs silently before market open',
        'Opening rally workflow',
        '09:00',
        'Radar Armed',
        '09:20',
        'Opening Rally Radar',
        '09:25',
        'Early Tradecards',
        '09:31',
        'Final Opening Confirmation',
    ):
        if label not in text:
            return _fail(f'/schedule missing {label!r}')
    for hidden in (
        'Morning builds & premarket',
        '07:45 — overnight global',
        '08:00 — India news',
        '08:15 — premarket scanner',
        '08:30 — Telegram premarket top 3',
        '08:45 — final premarket action',
    ):
        if hidden in text:
            return _fail(f'/schedule must hide legacy detail: {hidden!r}')
    return 0


def test_old_premarket_alerts_skipped() -> int:
    from io import StringIO
    from contextlib import redirect_stdout
    from backend.telegram.premarket_scheduler import run_premarket_slot

    with patch('backend.analytics.premarket_conviction.send_scheduled_premarket', return_value=True) as send_mock:
        buf = StringIO()
        with redirect_stdout(buf):
            ok = run_premarket_slot('premarket_top3', now=_dt(8, 30))
        if ok:
            return _fail('08:30 alert slot must not send when opening workflow enabled')
        if send_mock.called:
            return _fail('send_scheduled_premarket must not run for 08:30')
        if '[OLD_PREMARKET_ALERT_SKIPPED]' not in buf.getvalue() or 'alert=0830' not in buf.getvalue():
            return _fail('08:30 skip must log OLD_PREMARKET_ALERT_SKIPPED')
        buf2 = StringIO()
        with redirect_stdout(buf2):
            run_premarket_slot('premarket_action', now=_dt(8, 45))
        if send_mock.called:
            return _fail('send_scheduled_premarket must not run for 08:45')
        if 'alert=0845' not in buf2.getvalue():
            return _fail('08:45 skip must log OLD_PREMARKET_ALERT_SKIPPED')
    return 0


def test_silent_premarket_build_runs() -> int:
    from io import StringIO
    from contextlib import redirect_stdout
    from backend.telegram.premarket_scheduler import run_premarket_slot

    with patch('backend.analytics.premarket_conviction.build_premarket_conviction_report', return_value={}) as build_mock:
        buf = StringIO()
        with redirect_stdout(buf):
            ok = run_premarket_slot('overnight_global', now=_dt(7, 45))
        if not ok or not build_mock.called:
            return _fail('07:45 silent build must run build_premarket_conviction_report')
        logs = buf.getvalue()
        if '[SILENT_PREMARKET_BUILD]' not in logs or 'stage=global' not in logs:
            return _fail('07:45 must log SILENT_PREMARKET_BUILD stage=global')
        for slot, stage, hour, minute in (
            ('india_digest', 'news', 8, 0),
            ('scanner_build', 'scanner', 8, 15),
        ):
            buf = StringIO()
            with redirect_stdout(buf):
                run_premarket_slot(slot, now=_dt(hour, minute))
            if f'stage={stage}' not in buf.getvalue():
                return _fail(f'{slot} must log SILENT_PREMARKET_BUILD stage={stage}')
    return 0


def test_manual_premarket_still_works() -> int:
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    results = handle_analysis_command('/premarket', 'test', dry_run=True)
    text = str(results[0].get('text', '')).upper() if results else ''
    if not results or not any(token in text for token in ('PREMARKET', 'WEEKEND RESEARCH', 'LIVE MARKET', 'AFTER-HOURS')):
        return _fail('manual /premarket must still work')
    results_full = handle_analysis_command('/premarket full', 'test', dry_run=True)
    full_text = str(results_full[0].get('text', '')).upper() if results_full else ''
    if not results_full or 'BRIEF' not in full_text:
        return _fail('manual /premarket full must still work')
    return 0


def test_scheduled_radar_armed_0900() -> int:
    from io import StringIO
    from contextlib import redirect_stdout
    from backend.trading.opening_rally_radar import run_scheduled_radar_armed_0900

    fake_board = {
        'ranked_candidates': [
            {'ticker': 'RAILTEL', 'state': 'RADAR_ARMED', 'score': 68, 'why': ['fresh order win']},
        ],
        'time_ist': '09:00',
    }
    sent: list[str] = []

    def _send(text: str) -> bool:
        sent.append(text)
        return True

    with patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=fake_board), \
         patch('backend.orchestration.alert_quality_engine.evaluate_text_alert', return_value={'send': True}), \
         patch('backend.orchestration.alert_quality_engine.record_text_alert_sent'):
        buf = StringIO()
        with redirect_stdout(buf):
            ok = run_scheduled_radar_armed_0900(now=_dt(9, 0), send_fn=_send)
    if not ok or not sent:
        return _fail('09:00 radar armed must send when armed candidates exist')
    if 'RADAR ARMED' not in sent[0] and 'Radar Armed' not in sent[0]:
        return _fail('09:00 alert must use Radar Armed header')
    if '[OPENING_RADAR_ARMED_SCHEDULED]' not in buf.getvalue():
        return _fail('09:00 must log OPENING_RADAR_ARMED_SCHEDULED')
    return 0


def test_scheduled_early_tradecards_0925() -> int:
    from io import StringIO
    from contextlib import redirect_stdout
    from backend.trading.opening_rally_radar import run_scheduled_early_tradecards_0925

    fake_board = {
        'ranked_candidates': [
            {'ticker': 'RAILTEL', 'state': 'TRADECARD_CANDIDATE', 'score': 88, 'why': ['volume']},
            {'ticker': 'RVNL', 'state': 'VOLUME_IGNITION', 'score': 75, 'why': ['theme']},
        ],
        'time_ist': '09:25',
    }
    sent: list[str] = []

    def _send(text: str) -> bool:
        sent.append(text)
        return True

    with patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=fake_board), \
         patch('backend.trading.opening_rally_radar.pick_best_opening_tradecard', return_value=('RAILTEL', 88, ['RVNL'])), \
         patch('backend.orchestration.alert_quality_engine.evaluate_text_alert', return_value={'send': True}), \
         patch('backend.orchestration.alert_quality_engine.record_text_alert_sent'):
        buf = StringIO()
        with redirect_stdout(buf):
            ok = run_scheduled_early_tradecards_0925(now=_dt(9, 25), send_fn=_send)
    if not ok or 'Early Tradecards' not in sent[0]:
        return _fail('09:25 early tradecards must send ranked board')
    if 'Best provisional pick' not in sent[0] or 'RAILTEL' not in sent[0]:
        return _fail('09:25 must show provisional best pick')
    if '[EARLY_TRADECARDS_SCHEDULED]' not in buf.getvalue():
        return _fail('09:25 must log EARLY_TRADECARDS_SCHEDULED')
    return 0


def test_scheduled_final_confirmation_0931() -> int:
    from io import StringIO
    from contextlib import redirect_stdout
    from backend.trading.opening_rally_radar import run_scheduled_final_confirmation_0931

    fake_board = {
        'ranked_candidates': [
            {'ticker': 'RAILTEL', 'state': 'TRADECARD_CANDIDATE', 'score': 90, 'why': ['catalyst'], 'has_catalyst': True},
        ],
        'time_ist': '09:31',
    }
    sent: list[str] = []

    def _send(text: str) -> bool:
        sent.append(text)
        return True

    with patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=fake_board), \
         patch('backend.trading.opening_rally_radar.pick_best_opening_tradecard', return_value=('RAILTEL', 90, [])), \
         patch('backend.orchestration.alert_quality_engine.evaluate_text_alert', return_value={'send': True}), \
         patch('backend.orchestration.alert_quality_engine.record_text_alert_sent'):
        buf = StringIO()
        with redirect_stdout(buf):
            ok = run_scheduled_final_confirmation_0931(now=_dt(9, 31), send_fn=_send)
    if not ok or 'Final Opening Confirmation' not in sent[0]:
        return _fail('09:31 final confirmation must send')
    if 'Best pick' not in sent[0] or 'RAILTEL' not in sent[0]:
        return _fail('09:31 must show best pick')
    if '[FINAL_OPENING_CONFIRMATION]' not in buf.getvalue():
        return _fail('09:31 must log FINAL_OPENING_CONFIRMATION')
    return 0


def test_opening_sector_breadth_boosts_it_cluster() -> int:
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
        _row('INFY', 0.0, chg=4.1, price=154.0, open_price=148.0, vwap=150.0),
        _row('HCLTECH', 0.0, chg=3.2, price=102.0, open_price=99.0, vwap=100.0),
        _row('TCS', 0.0, chg=2.2, price=3900.0, open_price=3820.0, vwap=3850.0),
    )
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]):
        board = build_opening_rally_board(
            now=_dt(9, 20),
            catalyst_payload=catalyst,
            scanner_payload=scanner,
        )
    infy = next((r for r in board.get('ranked_candidates') or [] if r.get('ticker') == 'INFY'), None)
    hcl = next((r for r in board.get('ranked_candidates') or [] if r.get('ticker') == 'HCLTECH'), None)
    if not infy or (infy.get('sector_breadth') or {}).get('boost') != 12:
        return _fail(f'INFY should get IT breadth boost: {infy!r}')
    why = ' + '.join(infy.get('why') or [])
    if 'IT sector breadth confirmation' not in why:
        return _fail(f'INFY why should mention IT breadth: {why!r}')
    if 'railways metro theme' in why.lower():
        return _fail(f'INFY must not inherit railways metro theme: {why!r}')
    if infy.get('state') not in ('SECTOR_BREADTH_CONFIRM', 'PRICE_IGNITION', 'VOLUME_IGNITION'):
        return _fail(f'INFY strong price+breadth should not stay radar-only: {infy!r}')
    if not hcl or hcl.get('state') == 'REJECTED':
        return _fail(f'HCLTECH should be lifted by sector breadth: {hcl!r}')
    return 0


def test_chase_risk_best_becomes_pullback_only_plan() -> int:
    from backend.telegram.response_format import format_final_opening_confirmation_telegram
    from backend.trading.opening_rally_radar import resolve_final_confirmation_state

    row = {
        'ticker': 'INFY',
        'state': 'CHASE_RISK',
        'score': 88,
        'change_percent': 5.1,
        'has_catalyst': True,
        'why': ['result alert', 'IT sector breadth confirmation: INFY/HCLTECH/TCS'],
    }
    state = resolve_final_confirmation_state(row, now=_dt(9, 31))
    if state != 'PULLBACK_ONLY_PLAN':
        return _fail(f'CHASE_RISK strongest should become PULLBACK_ONLY_PLAN got {state}')
    text = format_final_opening_confirmation_telegram(
        board={'ranked_candidates': [row], 'time_ist': '09:31'},
        best_sym='INFY',
        best_score=88,
        confirm_state=state,
        best_row=row,
    )
    if 'PULLBACK ONLY PLAN' not in text or 'no chase' not in text.lower():
        return _fail(f'final confirmation missing pullback-only wording: {text}')
    return 0


def test_scheduled_best_pick_capture_and_no_fill() -> int:
    from io import StringIO
    from contextlib import redirect_stdout
    from backend.orchestration import alert_event_log
    from backend.trading import tradecard_journal as tcj
    from backend.trading.opening_rally_radar import run_scheduled_early_tradecards_0925

    fake_board = {
        'ranked_candidates': [
            {
                'ticker': 'INFY',
                'state': 'TRADECARD_CANDIDATE',
                'score': 91,
                'why': ['result alert', 'IT sector breadth confirmation: INFY/HCLTECH/TCS'],
                'change_percent': 4.8,
                'pullback_only': True,
                'scanner_row': {'price': 154.0, 'open_price': 148.0, 'vwap': 150.0, 'volume_ratio': 0.0},
            },
        ],
        'time_ist': '09:25',
    }
    sent: list[str] = []

    def _send(text: str) -> bool:
        sent.append(text)
        return True

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        alert_path = root / 'alert_event_log.jsonl'
        journal_path = root / 'tradecard_journal.jsonl'
        sample_path = root / 'tradecard_path_samples.jsonl'
        with patch.object(alert_event_log, 'ALERT_LOG_FILE', alert_path), \
             patch.object(tcj, 'JOURNAL_FILE', journal_path), \
             patch.object(tcj, 'PATH_SAMPLES_FILE', sample_path), \
             patch('backend.analytics.actual_learning_resolver.record_learning_candidate'), \
             patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=fake_board), \
             patch('backend.trading.opening_rally_radar.pick_best_opening_tradecard', return_value=('INFY', 91, [])), \
             patch('backend.orchestration.alert_quality_engine.evaluate_text_alert', return_value={'send': True}), \
             patch('backend.orchestration.alert_quality_engine.record_text_alert_sent'):
            buf = StringIO()
            with redirect_stdout(buf):
                ok = run_scheduled_early_tradecards_0925(now=_dt(9, 25), send_fn=_send)
            if not ok:
                return _fail('09:25 should send fixture')
            summary = alert_event_log.summarize_opening_workflow_for_date('2026-07-01')
            if summary.get('early_tradecard_best') != 'INFY':
                return _fail(f'09:25 best pick not captured: {summary!r}')
            counts = tcj.summarize_today_outcomes(session_date='2026-07-01').get('counts') or {}
            if counts.get('generated') != 1 or counts.get('pending') != 1:
                return _fail(f'opening best should create pending paper context: {counts!r}')
            resolved = tcj.resolve_close_pending_tradecards(session_date='2026-07-01', refresh=False)
            if resolved.get('no_fill') != 1 or resolved.get('pending') != 0:
                return _fail(f'opening paper context should resolve no-fill at close: {resolved!r}')
            logs = buf.getvalue()
            for token in ('[OPENING_WORKFLOW_CAPTURE]', '[OPENING_LEARNING_CAPTURE]', '[TRADECARD_GENERATED_FROM_OPENING_BEST]'):
                if token not in logs:
                    return _fail(f'missing opening capture log {token}: {logs}')
    return 0


def test_final_best_capture_and_daily_review_lines() -> int:
    from io import StringIO
    from contextlib import redirect_stdout
    from backend.orchestration import alert_event_log
    from backend.orchestration.alert_quality_engine import format_daily_review_quality_lines
    from backend.trading import tradecard_journal as tcj
    from backend.trading.opening_rally_radar import run_scheduled_final_confirmation_0931

    row = {
        'ticker': 'INFY',
        'state': 'CHASE_RISK',
        'score': 92,
        'why': ['result alert', 'IT sector breadth confirmation: INFY/HCLTECH/TCS'],
        'change_percent': 5.2,
        'has_catalyst': True,
        'pullback_only': True,
        'scanner_row': {'price': 155.0, 'open_price': 148.0, 'vwap': 150.0, 'volume_ratio': 0.0},
    }
    fake_board = {'ranked_candidates': [row], 'time_ist': '09:31'}
    sent: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        alert_path = root / 'alert_event_log.jsonl'
        journal_path = root / 'tradecard_journal.jsonl'
        sample_path = root / 'tradecard_path_samples.jsonl'
        with patch.object(alert_event_log, 'ALERT_LOG_FILE', alert_path), \
             patch.object(tcj, 'JOURNAL_FILE', journal_path), \
             patch.object(tcj, 'PATH_SAMPLES_FILE', sample_path), \
             patch('backend.analytics.actual_learning_resolver.record_learning_candidate'), \
             patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=fake_board), \
             patch('backend.trading.opening_rally_radar.pick_best_opening_tradecard', return_value=('INFY', 92, [])), \
             patch('backend.orchestration.alert_quality_engine.evaluate_text_alert', return_value={'send': True}), \
             patch('backend.orchestration.alert_quality_engine.record_text_alert_sent'):
            buf = StringIO()
            with redirect_stdout(buf):
                ok = run_scheduled_final_confirmation_0931(now=_dt(9, 31), send_fn=lambda text: sent.append(text) or True)
            if not ok or not sent:
                return _fail('09:31 should send fixture')
            summary = alert_event_log.summarize_opening_workflow_for_date('2026-07-01')
            if summary.get('final_confirmation_best') != 'INFY':
                return _fail(f'09:31 final best not captured: {summary!r}')
            with patch('backend.orchestration.alert_event_log.summarize_opening_workflow_for_date', return_value=summary), \
                 patch('backend.orchestration.alert_filters.get_telegram_alert_obs_summary', return_value={'recent_sent': []}), \
                 patch('backend.orchestration.alert_quality_engine.missed_opportunities_summary', return_value={'count': 0, 'rows': []}):
                lines = format_daily_review_quality_lines(
                    tradecard_counts={'generated': 1, 'filled': 0, 'pending': 1, 'no_fill': 0, 'valid_entry': 1},
                    actual_learning_summary={'sample_updated': 0, 'watchlist': {}, 'avoid': {}, 'pending_data': 0},
                )
            text = '\n'.join(lines)
            for needle in ('Opening workflow:', 'Final confirmation best: INFY', 'Learning candidate captured: INFY'):
                if needle not in text:
                    return _fail(f'daily review missing {needle!r}: {text}')
            if 'PULLBACK ONLY PLAN' not in sent[0] or 'no chase' not in sent[0].lower():
                return _fail(f'final confirmation should be pullback-only: {sent[0]}')
            if '[OPENING_PULLBACK_ONLY_PLAN]' not in buf.getvalue():
                return _fail(f'missing pullback-only log: {buf.getvalue()}')
    return 0


def test_opening_morning_scheduler_slots() -> int:
    from backend.telegram.premarket_scheduler import due_opening_morning_slots, run_opening_morning_slot

    due = due_opening_morning_slots(_dt(9, 20))
    if due != ['opening_radar_0920']:
        return _fail(f'expected opening_radar_0920 due at 09:20 got {due}')
    with patch('backend.trading.opening_rally_radar.run_opening_morning_scheduled_slot', return_value=True) as mock_run:
        run_opening_morning_slot('opening_radar_0920', now=_dt(9, 20))
        mock_run.assert_called_once()
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
        test_tradecard_selector_sync_with_tradecards,
        test_chase_risk_after_0940_no_active_entry,
        test_no_0910_scheduled_alert,
        test_schedule_shows_four_morning_alerts,
        test_old_premarket_alerts_skipped,
        test_silent_premarket_build_runs,
        test_manual_premarket_still_works,
        test_scheduled_radar_armed_0900,
        test_scheduled_opening_radar_candidates,
        test_scheduled_opening_radar_no_candidate_silent,
        test_scheduled_early_tradecards_0925,
        test_scheduled_final_confirmation_0931,
        test_opening_sector_breadth_boosts_it_cluster,
        test_chase_risk_best_becomes_pullback_only_plan,
        test_scheduled_best_pick_capture_and_no_fill,
        test_final_best_capture_and_daily_review_lines,
        test_opening_morning_scheduler_slots,
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
