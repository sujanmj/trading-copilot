#!/usr/bin/env python3
"""Phase 4B.18C — final-score rerank for /radar and /tradecards."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'FINAL_SCORE_RERANK_4B18C_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _row(ticker: str, *, score: int, **extra) -> dict:
    base = {
        'ticker': ticker,
        'state': 'TRADECARD_CANDIDATE',
        'score': score,
        'why': ['test'],
        'volume_ratio': 1.5,
        'catalyst_line': 'Catalyst: missing — price-volume only',
    }
    base.update(extra)
    return base


def _scores_from_tradecards(text: str) -> list[int]:
    scores: list[int] = []
    for line in text.splitlines():
        match = re.search(r'Score (\d+)', line)
        if match:
            scores.append(int(match.group(1)))
    return scores


def _scores_from_radar(text: str) -> list[int]:
    scores: list[int] = []
    for line in text.splitlines():
        match = re.search(r'Score: (\d+)', line)
        if match:
            scores.append(int(match.group(1)))
    return scores


def _unordered_board() -> dict:
    return {
        'session_date': '2026-07-08',
        'time_ist': '09:25',
        'phase': 'CONFIRMATION',
        'data_status': 'current',
        'ranked_candidates': [
            _row('TEXRAIL', score=74),
            _row('ANDHRSUGAR', score=72),
            _row('HTMEDIA', score=78, has_catalyst=False, catalyst_state='PRICE_VOLUME_ONLY'),
            _row('INDUSINDBK', score=70),
        ],
    }


def test_tradecards_scores_descending() -> int:
    from backend.telegram.response_format import format_tradecards_telegram

    text = format_tradecards_telegram(board=_unordered_board())
    scores = _scores_from_tradecards(text)
    if scores != sorted(scores, reverse=True):
        return _fail(f'/tradecards must list scores descending got {scores!r}')
    if scores[0] != 78:
        return _fail(f'HTMEDIA 78 must be first got {scores!r}')
    return 0


def test_radar_scores_descending() -> int:
    from backend.telegram.response_format import format_opening_radar_telegram

    text = format_opening_radar_telegram(board=_unordered_board())
    scores = _scores_from_radar(text)
    if scores != sorted(scores, reverse=True):
        return _fail(f'/radar must list scores descending got {scores!r}')
    return 0


def test_pattern_boost_moves_candidate_up() -> int:
    from backend.telegram.response_format import format_tradecards_telegram
    from backend.trading.opening_rally_radar import rerank_opening_candidates

    board = {
        'session_date': '2026-07-08',
        'ranked_candidates': [
            _row('TEXRAIL', score=74),
            _row('HTMEDIA', score=70, pattern_boost=8),
        ],
    }
    board['ranked_candidates'][1]['score'] = 78
    ranked = rerank_opening_candidates(board['ranked_candidates'])
    if ranked[0].get('ticker') != 'HTMEDIA':
        return _fail('pattern-boosted HTMEDIA must rank above TEXRAIL after rerank')
    text = format_tradecards_telegram(board={**board, 'ranked_candidates': ranked})
    if '1. <b>HTMEDIA</b>' not in text:
        return _fail('HTMEDIA must appear first on /tradecards after pattern boost')
    return 0


def test_catalyst_beats_theme_only_same_score() -> int:
    from backend.trading.opening_rally_radar import rerank_opening_candidates

    ranked = rerank_opening_candidates([
        _row('THEMEONLY', score=80, themes=['defence'], catalyst_state='THEME_ONLY'),
        _row('BEL', score=80, has_catalyst=True, catalyst_state='CATALYST_CONFIRMED',
             catalyst_line='Catalyst: confirmed — broker/order alert'),
    ])
    if ranked[0].get('ticker') != 'BEL':
        return _fail(f'catalyst-confirmed must beat theme-only at same score got {[r.get("ticker") for r in ranked]!r}')
    return 0


def test_best_pick_equals_rank_one() -> int:
    from backend.telegram.response_format import format_tradecards_telegram
    from backend.trading.opening_rally_radar import pick_best_opening_tradecard

    board = _unordered_board()
    best_sym, _, _ = pick_best_opening_tradecard(board)
    text = format_tradecards_telegram(board=board)
    if best_sym != 'HTMEDIA':
        return _fail(f'expected best pick HTMEDIA got {best_sym!r}')
    if f'1. <b>{best_sym}</b>' not in text:
        return _fail('best pick must be rank 1 line on /tradecards')
    if f'<b>Best pick:</b> {best_sym}' not in text:
        return _fail('best pick footer must match rank 1 symbol')
    return 0


def test_tiebreak_deterministic() -> int:
    from backend.trading.opening_rally_radar import rerank_opening_candidates

    rows = [
        {**_row('ZETA', score=55), 'tradecards_rank': 5},
        {**_row('ALPHA', score=55), 'tradecards_rank': 5},
    ]
    first = rerank_opening_candidates([dict(r) for r in rows])
    second = rerank_opening_candidates(list(reversed([dict(r) for r in rows])))
    if [r.get('ticker') for r in first] != [r.get('ticker') for r in second]:
        return _fail('symbol tie-break must be deterministic')
    if first[0].get('ticker') != 'ALPHA':
        return _fail('ALPHA must win alphabetical tie-break over ZETA')
    return 0


def test_merged_risk_line() -> int:
    from backend.telegram.response_format import _format_candidate_risk_line

    row = _row(
        'CHASEME',
        score=60,
        state='CHASE_RISK',
        pullback_only=True,
        catalyst_risk_line='Risk: catalyst not found — confirm manually; no blind chase',
    )
    line = _format_candidate_risk_line(row)
    expected = 'Risk: catalyst not found + extended/chase — confirm manually; VWAP/retest only; no blind chase.'
    if line != expected:
        return _fail(f'expected merged risk line {expected!r} got {line!r}')
    return 0


def _run(script: str) -> int:
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / script)],
        cwd=str(PROJECT_ROOT),
        check=False,
    ).returncode


def test_regression_catalyst_4b18() -> int:
    if _run('test_catalyst_gainer_classification_4b18.py') != 0:
        return _fail('catalyst 4B.18 regression failed')
    return 0


def test_regression_opening_workflow_4b18b() -> int:
    if _run('test_opening_workflow_accounting_4b18b.py') != 0:
        return _fail('opening workflow 4B.18B regression failed')
    return 0


def test_regression_qa_smoke_4b18a() -> int:
    if _run('test_qa_smoke_isolation_4b18a.py') != 0:
        return _fail('QA smoke isolation 4B.18A regression failed')
    return 0


def test_regression_pattern_board() -> int:
    for script in ('test_pattern_board_4b17a.py', 'test_pattern_board_consistency_4b17b.py'):
        if _run(script) != 0:
            return _fail(f'{script} regression failed')
    return 0


def test_build_label_52a() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52G' or ASTRAEDGE_BUILD_STAGE != '52G':
        return _fail(f'expected AstraEdge 52G got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_tradecards_scores_descending,
        test_radar_scores_descending,
        test_pattern_boost_moves_candidate_up,
        test_catalyst_beats_theme_only_same_score,
        test_best_pick_equals_rank_one,
        test_tiebreak_deterministic,
        test_merged_risk_line,
        test_regression_catalyst_4b18,
        test_regression_opening_workflow_4b18b,
        test_regression_qa_smoke_4b18a,
        test_regression_pattern_board,
        test_build_label_52a,
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
    print('FINAL_SCORE_RERANK_4B18C_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
