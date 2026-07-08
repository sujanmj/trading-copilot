#!/usr/bin/env python3
"""Phase 4B.18D — live confirmation guard for opening workflow."""

from __future__ import annotations

import os
import subprocess
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
SESSION = '2026-07-08'


def _fail(msg: str) -> int:
    print(f'LIVE_CONFIRMATION_GUARD_4B18D_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _now() -> datetime:
    return datetime(2026, 7, 8, 9, 31, tzinfo=IST)


def _board(candidates: list[dict], **extra) -> dict:
    payload = {
        'session_date': SESSION,
        'time_ist': '09:31',
        'phase': 'CONFIRMATION',
        'data_status': 'current',
        'ranked_candidates': candidates,
        'macro_penalty': 0,
    }
    payload.update(extra)
    return payload


def _stale_catalyst_bel() -> dict:
    return {
        'ticker': 'BEL',
        'state': 'TRADECARD_CANDIDATE',
        'score': 72,
        'why': ['defence order win', 'defence theme'],
        'has_catalyst': True,
        'themes': ['defence'],
        'catalyst_state': 'CATALYST_CONFIRMED',
        'catalyst': {
            'ticker': 'BEL',
            'catalyst_type': 'ORDER_WIN',
            'side': 'BULLISH',
            'headline': 'old BEL order win',
            'published_at': '2026-07-07T08:00:00+05:30',
            'freshness_label': 'previous_day',
        },
        # Explicitly no live scanner/price for confirmation.
    }


def _live_confirmed_row(sym: str = 'HTMEDIA', *, score: int = 78) -> dict:
    return {
        'ticker': sym,
        'state': 'TRADECARD_CANDIDATE',
        'score': score,
        'why': ['top gainer', 'volume 2.2x'],
        'has_catalyst': True,
        'catalyst_state': 'CATALYST_CONFIRMED',
        'catalyst': {
            'ticker': sym,
            'catalyst_type': 'RESULT',
            'side': 'BULLISH',
            'headline': f'{sym} result today',
            'published_at': f'{SESSION}T08:45:00+05:30',
            'freshness_label': 'today',
        },
        'volume_ratio': 2.2,
        'change_percent': 3.5,
        'gainer_promoted': True,
        'scanner_row': {
            'ticker': sym,
            'price': 100.0,
            'open_price': 97.0,
            'vwap': 98.0,
            'change_percent': 3.5,
            'volume_ratio': 2.2,
            'direction': 'BULLISH',
            'session_date': SESSION,
            'timestamp': f'{SESSION}T09:25:00+05:30',
        },
    }


def test_cannot_confirm_old_catalyst_without_scanner() -> int:
    from backend.trading.live_confirmation_guard import evaluate_live_confirmation

    verdict = evaluate_live_confirmation(_stale_catalyst_bel(), now=_now(), board=_board([]))
    if verdict.get('state') == 'CONFIRMED':
        return _fail('old catalyst without scanner must not CONFIRM')
    if verdict.get('state') not in ('WAIT_LIVE_CONFIRM', 'NO_TRADE', 'WATCH_ONLY'):
        return _fail(f'expected wait/no-trade/watch got {verdict.get("state")!r}')
    return 0


def test_bel_downgrades_when_scanner_missing() -> int:
    from backend.trading.live_confirmation_guard import select_final_confirmation_pick
    from backend.trading.opening_rally_radar import resolve_final_confirmation_state

    board = _board([_stale_catalyst_bel()])
    pick = select_final_confirmation_pick(board, now=_now())
    if pick.get('confirm_state') == 'CONFIRMED':
        return _fail('09:31 must not CONFIRM BEL without live scanner')
    state = resolve_final_confirmation_state(_stale_catalyst_bel(), now=_now(), board=board)
    if state not in ('WAIT_LIVE_CONFIRM', 'NO_TRADE'):
        return _fail(f'BEL must downgrade to WAIT_LIVE_CONFIRM/NO_TRADE got {state!r}')
    return 0


def test_tradecard_reject_aligns_with_0931() -> int:
    from backend.trading.live_confirmation_guard import evaluate_live_confirmation

    # Mirrors /tradecard: no scanner candidate → NO_TRADE / research watch only.
    row = {
        'ticker': 'BEL',
        'state': 'TRADECARD_CANDIDATE',
        'score': 70,
        'has_catalyst': False,
        'why': ['defence theme'],
        'themes': ['defence'],
    }
    verdict = evaluate_live_confirmation(row, now=_now(), board=_board([]))
    if verdict.get('state') == 'CONFIRMED':
        return _fail('theme-only without scanner must not CONFIRM (aligns with /tradecard reject)')
    if verdict.get('state') not in ('WATCH_ONLY', 'NO_TRADE', 'WAIT_LIVE_CONFIRM'):
        return _fail(f'expected non-confirm state got {verdict.get("state")!r}')
    return 0


def test_fresh_catalyst_negative_price_no_confirm() -> int:
    from backend.trading.live_confirmation_guard import evaluate_live_confirmation

    row = _live_confirmed_row('BEL', score=75)
    row['scanner_row'] = {
        **row['scanner_row'],
        'change_percent': -2.8,
        'price': 95.0,
        'open_price': 100.0,
        'vwap': 98.0,
        'direction': 'BEARISH',
    }
    row['change_percent'] = -2.8
    verdict = evaluate_live_confirmation(row, now=_now(), board=_board([]))
    if verdict.get('state') == 'CONFIRMED':
        return _fail('fresh catalyst + negative price must not CONFIRM')
    if verdict.get('state') != 'NO_TRADE':
        return _fail(f'expected NO_TRADE for invalid price got {verdict.get("state")!r}')
    return 0


def test_macro_crash_blocks_stale_catalyst() -> int:
    from backend.trading.live_confirmation_guard import evaluate_live_confirmation

    board = _board([_stale_catalyst_bel()], macro_penalty=15, emergency_macro=True)
    verdict = evaluate_live_confirmation(_stale_catalyst_bel(), now=_now(), board=board)
    if verdict.get('state') == 'CONFIRMED':
        return _fail('macro crash must block stale catalyst confirmation')
    if verdict.get('state') not in ('NO_TRADE', 'WAIT_LIVE_CONFIRM'):
        return _fail(f'expected NO_TRADE/WAIT under crash got {verdict.get("state")!r}')
    return 0


def test_0925_labels_catalyst_only_watch() -> int:
    from backend.telegram.response_format import format_early_tradecards_scheduled_telegram

    board = {
        'session_date': SESSION,
        'time_ist': '09:25',
        'ranked_candidates': [_stale_catalyst_bel()],
    }
    text = format_early_tradecards_scheduled_telegram(board=board)
    if 'WAIT LIVE CONFIRM' not in text and 'WATCH ONLY' not in text:
        return _fail('09:25 must label catalyst-only candidate as WATCH ONLY / WAIT LIVE CONFIRM')
    if 'TRADECARD CANDIDATE' in text and 'WAIT LIVE CONFIRM' not in text:
        # Strict: catalyst-only should not be shown as full TRADECARD CANDIDATE alone.
        return _fail('catalyst-only must not appear as TRADECARD CANDIDATE without live support')
    return 0


def test_no_candidates_outputs_no_trade() -> int:
    from backend.telegram.response_format import format_final_opening_confirmation_telegram
    from backend.trading.live_confirmation_guard import select_final_confirmation_pick

    board = _board([_stale_catalyst_bel()])
    pick = select_final_confirmation_pick(board, now=_now())
    text = format_final_opening_confirmation_telegram(
        board=board,
        best_sym=str(pick.get('best_sym') or ''),
        best_score=int(pick.get('best_score') or 0),
        confirm_state=str(pick.get('confirm_state') or 'NO_TRADE'),
        best_row=pick.get('best_row') if isinstance(pick.get('best_row'), dict) else {},
        watch_sym=str(pick.get('watch_sym') or ''),
        reason=str(pick.get('reason') or ''),
        no_trade=bool(pick.get('no_trade')),
    )
    if 'NO TRADE' not in text.upper() and 'WAIT LIVE CONFIRM' not in text.upper():
        return _fail('final output must say NO TRADE or WAIT LIVE CONFIRM when gate fails')
    if pick.get('confirm_state') == 'CONFIRMED':
        return _fail('no live-passing candidate must not CONFIRM')
    return 0


def test_live_scanner_can_confirm() -> int:
    from backend.trading.live_confirmation_guard import evaluate_live_confirmation, select_final_confirmation_pick

    live = _live_confirmed_row('HTMEDIA')
    verdict = evaluate_live_confirmation(live, now=_now(), board=_board([live]))
    if verdict.get('state') != 'CONFIRMED':
        return _fail(f'fresh live scanner + volume must CONFIRM got {verdict!r}')
    pick = select_final_confirmation_pick(_board([_stale_catalyst_bel(), live]), now=_now())
    if pick.get('confirm_state') != 'CONFIRMED':
        return _fail(f'expected HTMEDIA CONFIRMED pick got {pick.get("confirm_state")!r}')
    if pick.get('best_sym') != 'HTMEDIA':
        return _fail(f'expected best_sym HTMEDIA got {pick.get("best_sym")!r}')
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


def test_build_label_52b() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52D' or ASTRAEDGE_BUILD_STAGE != '52D':
        return _fail(f'expected AstraEdge 52D got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_cannot_confirm_old_catalyst_without_scanner,
        test_bel_downgrades_when_scanner_missing,
        test_tradecard_reject_aligns_with_0931,
        test_fresh_catalyst_negative_price_no_confirm,
        test_macro_crash_blocks_stale_catalyst,
        test_0925_labels_catalyst_only_watch,
        test_no_candidates_outputs_no_trade,
        test_live_scanner_can_confirm,
        test_regression_final_score_rerank_4b18c,
        test_regression_opening_workflow_4b18b,
        test_regression_qa_smoke_4b18a,
        test_regression_catalyst_4b18,
        test_build_label_52b,
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
    print('LIVE_CONFIRMATION_GUARD_4B18D_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
