#!/usr/bin/env python3
"""AstraEdge 52L — final opening confirmation quality gate at 09:31."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

IST = ZoneInfo('Asia/Kolkata')
SESSION = '2026-07-10'


def _fail(msg: str) -> int:
    print(f'OPENING_CONFIRMATION_QUALITY_52L_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _now() -> datetime:
    return datetime(2026, 7, 10, 9, 31, tzinfo=IST)


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


def _weak_live_row(sym: str = 'STYLAMIND', *, score: int = 24) -> dict:
    return {
        'ticker': sym,
        'state': 'TRADECARD_CANDIDATE',
        'score': score,
        'why': ['live scanner reaction'],
        'has_catalyst': False,
        'change_percent': 1.8,
        'volume_ratio': 1.5,
        'gainer_promoted': True,
        'scanner_row': {
            'ticker': sym,
            'price': 180.0,
            'open_price': 177.0,
            'vwap': 178.0,
            'change_percent': 1.8,
            'volume_ratio': 1.5,
            'direction': 'BULLISH',
            'session_date': SESSION,
            'timestamp': f'{SESSION}T09:28:00+05:30',
        },
    }


def _quality_live_row(sym: str = 'HTMEDIA', *, score: int = 72) -> dict:
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


def test_score_24_cannot_be_confirmed() -> int:
    from backend.telegram.response_format import format_final_opening_confirmation_telegram
    from backend.trading.live_confirmation_guard import evaluate_live_confirmation, select_final_confirmation_pick

    row = _weak_live_row()
    board = _board([row], early_tradecards_had_quality=False)
    verdict = evaluate_live_confirmation(row, now=_now(), board=board)
    if verdict.get('state') == 'CONFIRMED':
        return _fail('score 24 must not be CONFIRMED')
    if verdict.get('state') != 'WATCH_ONLY':
        return _fail(f'expected WATCH_ONLY for score 24 got {verdict.get("state")!r}')

    pick = select_final_confirmation_pick(board, now=_now())
    if pick.get('confirm_state') == 'CONFIRMED':
        return _fail('09:31 pick must not CONFIRM score 24')
    text = format_final_opening_confirmation_telegram(
        board=board,
        best_sym=str(pick.get('best_sym') or ''),
        best_score=int(pick.get('best_score') or 0),
        confirm_state=str(pick.get('confirm_state') or ''),
        best_row=pick.get('best_row') if isinstance(pick.get('best_row'), dict) else {},
        watch_sym=str(pick.get('watch_sym') or ''),
        reason=str(pick.get('reason') or ''),
        no_trade=bool(pick.get('no_trade')),
        macro_guard=bool(pick.get('macro_guard')),
    )
    if 'CONFIRMED' in text.upper() and 'WATCH' not in text.upper():
        return _fail('output must not label weak candidate CONFIRMED')
    if 'STYLAMIND' not in text:
        return _fail('weak candidate must remain visible in watch output')
    if 'quality threshold 60' not in text.lower() and 'below quality threshold' not in text.lower():
        return _fail('output must explain score below quality threshold')
    return 0


def test_red_macro_requires_stronger_threshold() -> int:
    from backend.trading.live_confirmation_guard import evaluate_live_confirmation, select_final_confirmation_pick

    row = _quality_live_row(score=62)
    row['has_catalyst'] = False
    row['catalyst'] = {}
    row.pop('catalyst_state', None)
    board = _board([row], emergency_macro=True, macro_penalty=15)
    verdict = evaluate_live_confirmation(row, now=_now(), board=board)
    if verdict.get('state') == 'CONFIRMED':
        return _fail('score 62 must not CONFIRM under red macro without stronger evidence')
    if verdict.get('state') != 'WATCH_ONLY':
        return _fail(f'expected WATCH_ONLY under red macro got {verdict.get("state")!r}')

    strong = _quality_live_row(score=66)
    strong_verdict = evaluate_live_confirmation(strong, now=_now(), board=board)
    if strong_verdict.get('state') != 'CONFIRMED':
        return _fail(f'score 66 with live confirmation should CONFIRM under red macro got {strong_verdict!r}')

    rs_row = _quality_live_row(score=62)
    pick = select_final_confirmation_pick(_board([rs_row], emergency_macro=True), now=_now())
    if pick.get('confirm_state') != 'CONFIRMED':
        return _fail('score 62 with RS + volume + catalyst may CONFIRM under red macro')
    return 0


def test_score_60_with_live_confirmation_can_confirm() -> int:
    from backend.trading.live_confirmation_guard import evaluate_live_confirmation, select_final_confirmation_pick

    row = _quality_live_row(score=60)
    board = _board([row])
    verdict = evaluate_live_confirmation(row, now=_now(), board=board)
    if verdict.get('state') != 'CONFIRMED':
        return _fail(f'score 60 with live confirmation must CONFIRM got {verdict.get("state")!r}')
    pick = select_final_confirmation_pick(board, now=_now())
    if pick.get('confirm_state') != 'CONFIRMED':
        return _fail(f'expected CONFIRMED pick got {pick.get("confirm_state")!r}')
    return 0


def test_0925_no_quality_does_not_force_0931_confirmation() -> int:
    from backend.trading.live_confirmation_guard import select_final_confirmation_pick

    weak = _weak_live_row(score=24)
    board = _board([weak], early_tradecards_had_quality=False)
    pick = select_final_confirmation_pick(board, now=_now())
    if pick.get('confirm_state') == 'CONFIRMED':
        return _fail('09:25 no-quality must not force 09:31 CONFIRMED for score 24')

    upgraded = _quality_live_row(score=63)
    upgraded_board = _board([upgraded], early_tradecards_had_quality=False)
    upgraded_pick = select_final_confirmation_pick(upgraded_board, now=_now())
    if upgraded_pick.get('confirm_state') != 'CONFIRMED':
        return _fail('new candidate crossing threshold at 09:31 should CONFIRM')
    return 0


def test_build_label_52l() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52L' or ASTRAEDGE_BUILD_STAGE != '52L':
        return _fail(f'expected AstraEdge 52L got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    checks = (
        test_score_24_cannot_be_confirmed,
        test_red_macro_requires_stronger_threshold,
        test_score_60_with_live_confirmation_can_confirm,
        test_0925_no_quality_does_not_force_0931_confirmation,
        test_build_label_52l,
    )
    for check in checks:
        err = check()
        if err:
            return err
    print('OPENING_CONFIRMATION_QUALITY_52L_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
