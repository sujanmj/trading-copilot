#!/usr/bin/env python3
"""Phase 4B.18E — Overnight Macro Shock Sentinel (AstraEdge 52E)."""

from __future__ import annotations

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
SESSION = '2026-07-08'
OVERNIGHT = datetime(2026, 7, 8, 6, 30, tzinfo=IST)
PREOPEN_0900 = datetime(2026, 7, 8, 9, 0, tzinfo=IST)
CONFIRM_0931 = datetime(2026, 7, 8, 9, 31, tzinfo=IST)

IRAN_HEADLINE = (
    'Inshorts: Trump said Iran ceasefire is over after missile strike; '
    'Reuters confirms Middle East escalation risk'
)
OIL_HEADLINE = 'Reuters: Brent crude jumps nearly 6% on supply disruption and Hormuz risk'
COMBINED_HEADLINE = (
    'AP: Trump Iran ceasefire over; crude oil jumped nearly 6%; '
    'Sensex/Nifty gap-down risk as Gift Nifty points lower'
)


def _fail(msg: str) -> int:
    print(f'MACRO_SHOCK_SENTINEL_4B18E_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


@contextmanager
def _isolated_macro_env():
    import sqlite3

    import backend.my_feed.my_feed_db as db_mod

    uri = 'file:macro_shock_test_mem?mode=memory&cache=shared'
    boot = sqlite3.connect(uri, uri=True, check_same_thread=False)
    boot.row_factory = sqlite3.Row
    boot.executescript(db_mod.SCHEMA)
    boot.commit()
    boot.close()

    def _mem_connect() -> sqlite3.Connection:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        state_path = Path(tmp) / 'macro_shock_sentinel_state.json'
        with patch('backend.trading.macro_shock_sentinel.STATE_FILE', state_path), patch.object(
            db_mod, '_connect', _mem_connect
        ):
            db_mod.init_my_feed_db()
            yield state_path, Path(':memory:')


def test_trump_iran_ceasefire_critical() -> int:
    from backend.trading.macro_shock_sentinel import SEVERITY_CRITICAL, score_macro_severity

    result = score_macro_severity(IRAN_HEADLINE)
    if result.get('severity') != SEVERITY_CRITICAL:
        return _fail(f'expected CRITICAL for Iran ceasefire got {result.get("severity")!r}')
    if 'Iran' not in (result.get('themes') or []):
        return _fail('expected Iran theme')
    return 0


def test_crude_oil_six_percent_critical() -> int:
    from backend.trading.macro_shock_sentinel import SEVERITY_CRITICAL, score_macro_severity

    result = score_macro_severity(OIL_HEADLINE)
    if result.get('severity') != SEVERITY_CRITICAL:
        return _fail(f'expected CRITICAL oil shock got {result.get("severity")!r}')
    if result.get('oil_pct') is None or float(result.get('oil_pct')) < 6:
        return _fail(f'expected oil_pct>=6 got {result.get("oil_pct")!r}')
    return 0


def test_geo_oil_sends_alert_outside_market_hours() -> int:
    from backend.trading.macro_shock_sentinel import process_macro_headline

    sent_messages: list[str] = []

    def _send(text: str) -> bool:
        sent_messages.append(text)
        return True

    with _isolated_macro_env():
        result = process_macro_headline(
            COMBINED_HEADLINE,
            source='Reuters',
            send_fn=_send,
            slot='immediate',
        )
    if not result.get('sent'):
        return _fail('expected Telegram alert outside market hours')
    if not sent_messages or 'MACRO SHOCK' not in sent_messages[0]:
        return _fail('alert text missing MACRO SHOCK header')
    return 0


def test_macro_shock_stored_in_feed_memory() -> int:
    from backend.my_feed.my_feed_db import list_items
    from backend.trading.macro_shock_sentinel import process_macro_headline

    with _isolated_macro_env():
        process_macro_headline(COMBINED_HEADLINE, source='Inshorts', send_fn=None)
        rows = list_items(limit=10, today_only=False)
    if not rows:
        return _fail('expected macro shock row in my_feed')
    row = rows[0]
    if row.get('source') != 'macro_shock_sentinel':
        return _fail(f'expected source macro_shock_sentinel got {row.get("source")!r}')
    if row.get('event_type') != 'macro_shock':
        return _fail(f'expected event_type macro_shock got {row.get("event_type")!r}')
    return 0


def test_macro_command_shows_red_market() -> int:
    from backend.trading.macro_shock_sentinel import format_macro_command_telegram, process_macro_headline

    with _isolated_macro_env():
        process_macro_headline(COMBINED_HEADLINE, source='Reuters', send_fn=None)
        text = format_macro_command_telegram('')
    upper = text.upper()
    if 'RED MARKET' not in upper and 'GAP-DOWN' not in upper:
        return _fail(f'/macro missing RED MARKET / GAP-DOWN RISK: {text[:200]!r}')
    return 0


def test_radar_armed_includes_macro_warning() -> int:
    from backend.telegram.response_format import format_radar_armed_scheduled_telegram
    from backend.trading.macro_shock_sentinel import apply_macro_shock_to_board, process_macro_headline

    with _isolated_macro_env():
        process_macro_headline(COMBINED_HEADLINE, source='Reuters', send_fn=None)
        board = apply_macro_shock_to_board(
            {
                'time_ist': '09:00',
                'ranked_candidates': [
                    {'ticker': 'ONGC', 'state': 'RADAR_ARMED', 'score': 58, 'why': ['oil']},
                ],
            },
            now=PREOPEN_0900,
        )
        text = format_radar_armed_scheduled_telegram(board=board)
    if 'Macro regime' not in text:
        return _fail('09:00 radar armed missing macro regime warning')
    return 0


def test_final_confirmation_blocks_stale_catalyst_during_macro_shock() -> int:
    from backend.trading.live_confirmation_guard import select_final_confirmation_pick
    from backend.trading.macro_shock_sentinel import apply_macro_shock_to_board, process_macro_headline

    stale_bel = {
        'ticker': 'BEL',
        'state': 'TRADECARD_CANDIDATE',
        'score': 72,
        'why': ['defence order win'],
        'has_catalyst': True,
        'catalyst': {
            'headline': 'old BEL order win',
            'published_at': '2026-07-07T08:00:00+05:30',
            'freshness_label': 'previous_day',
        },
    }
    with _isolated_macro_env():
        process_macro_headline(COMBINED_HEADLINE, source='Reuters', send_fn=None)
        board = apply_macro_shock_to_board(
            {'ranked_candidates': [stale_bel], 'session_date': SESSION},
            now=CONFIRM_0931,
        )
        pick = select_final_confirmation_pick(board, now=CONFIRM_0931)
    if pick.get('confirm_state') == 'CONFIRMED':
        return _fail('stale catalyst must not CONFIRM during macro shock')
    if not pick.get('no_trade') and pick.get('confirm_state') not in ('NO_TRADE', 'WAIT_LIVE_CONFIRM'):
        return _fail(f'expected NO_TRADE/WAIT got {pick.get("confirm_state")!r}')
    return 0


def test_dedupe_prevents_repeated_alert() -> int:
    from backend.trading.macro_shock_sentinel import process_macro_headline

    sent_count = 0

    def _send(_text: str) -> bool:
        nonlocal sent_count
        sent_count += 1
        return True

    with _isolated_macro_env():
        first = process_macro_headline(COMBINED_HEADLINE, source='Reuters', send_fn=_send)
        second = process_macro_headline(COMBINED_HEADLINE, source='Reuters', send_fn=_send)
    if not first.get('sent'):
        return _fail('first alert should send')
    if second.get('sent'):
        return _fail('duplicate headline should not resend')
    if sent_count != 1:
        return _fail(f'expected 1 send got {sent_count}')
    return 0


def test_stronger_source_updates_severity() -> int:
    from backend.trading.macro_shock_sentinel import SEVERITY_HIGH, process_macro_headline, score_macro_severity

    weaker = 'Middle East escalation risk rising'
    with _isolated_macro_env():
        weak_score = score_macro_severity(weaker)
        if weak_score.get('severity') not in ('WATCH', 'HIGH'):
            return _fail(f'unexpected weak severity {weak_score.get("severity")!r}')
        process_macro_headline(weaker, source='blog', send_fn=None)
        upgraded = process_macro_headline(COMBINED_HEADLINE, source='Reuters', send_fn=None)
        active = upgraded.get('assessment') or {}
    if active.get('severity') not in ('HIGH', 'CRITICAL'):
        return _fail(f'expected upgraded HIGH/CRITICAL got {active.get("severity")!r}')
    if SEVERITY_HIGH not in ('HIGH', 'CRITICAL'):
        pass
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


def test_regression_live_confirmation_guard_4b18d() -> int:
    if _run('test_live_confirmation_guard_4b18d.py') != 0:
        return _fail('52B live confirmation guard regression failed')
    return 0


def test_regression_final_score_rerank_4b18c() -> int:
    if _run('test_final_score_rerank_4b18c.py') != 0:
        return _fail('52A final-score rerank regression failed')
    return 0


def test_regression_opening_workflow_4b18b() -> int:
    if _run('test_opening_workflow_accounting_4b18b.py') != 0:
        return _fail('4B.18B opening workflow accounting regression failed')
    return 0


def test_regression_qa_smoke_4b18a() -> int:
    if _run('test_qa_smoke_isolation_4b18a.py') != 0:
        return _fail('4B.18A QA smoke isolation regression failed')
    return 0


def test_regression_catalyst_4b18() -> int:
    if _run('test_catalyst_gainer_classification_4b18.py') != 0:
        return _fail('catalyst classification 4B.18 regression failed')
    return 0


def test_build_label_52c() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52E' or ASTRAEDGE_BUILD_STAGE != '52E':
        return _fail(f'expected AstraEdge 52E got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_trump_iran_ceasefire_critical,
        test_crude_oil_six_percent_critical,
        test_geo_oil_sends_alert_outside_market_hours,
        test_macro_shock_stored_in_feed_memory,
        test_macro_command_shows_red_market,
        test_radar_armed_includes_macro_warning,
        test_final_confirmation_blocks_stale_catalyst_during_macro_shock,
        test_dedupe_prevents_repeated_alert,
        test_stronger_source_updates_severity,
        test_regression_live_confirmation_guard_4b18d,
        test_regression_final_score_rerank_4b18c,
        test_regression_opening_workflow_4b18b,
        test_regression_qa_smoke_4b18a,
        test_regression_catalyst_4b18,
        test_build_label_52c,
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
    print('MACRO_SHOCK_SENTINEL_4B18E_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
