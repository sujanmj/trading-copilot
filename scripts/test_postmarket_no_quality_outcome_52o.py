#!/usr/bin/env python3
"""AstraEdge 52O — post-market outcome review integrity."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'POSTMARKET_NO_QUALITY_OUTCOME_52O_FAIL: {msg}', file=sys.stderr)
    return 1


def _paths(tmp: Path) -> dict[str, Path]:
    return {
        'snapshots': tmp / 'candidate_snapshots.jsonl',
        'outcomes': tmp / 'candidate_outcomes.jsonl',
        'learning': tmp / 'candidate_learning_records.jsonl',
        'state': tmp / 'candidate_outcome_learning_state.json',
    }


def _patch_paths(paths: dict[str, Path]):
    return patch.multiple(
        'backend.trading.candidate_outcome_learning',
        _snapshots_path=lambda: paths['snapshots'],
        _outcomes_path=lambda: paths['outcomes'],
        _learning_path=lambda: paths['learning'],
        _state_path=lambda: paths['state'],
    )


def test_build_label_52o() -> int:
    from scripts.test_build_helpers import assert_canonical_build, expected_build_label

    err = assert_canonical_build(_fail)
    if err:
        return err
    if not expected_build_label().startswith('AstraEdge 52'):
        return _fail(f'unexpected build label {expected_build_label()!r}')
    return 0


def test_radar_only_skipped() -> int:
    from backend.trading.candidate_outcome_learning import (
        capture_quality_snapshots,
        eligible_snapshots_for_session,
        is_outcome_learning_eligible,
        outcome_learning_skip_reason,
    )

    row = {'ticker': 'BAJAJCON', 'score': 72, 'state': 'RADAR_ARMED', 'why': ['theme watch']}
    if is_outcome_learning_eligible(row):
        return _fail('RADAR_ARMED must not be eligible')
    if outcome_learning_skip_reason(row) != 'watch_only':
        return _fail('RADAR_ARMED skip reason must be watch_only')

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = _paths(Path(tmpdir))
        board = {
            'session_date': '2026-07-10',
            'scanner_freshness_status': 'CURRENT',
            'ranked_candidates': [row],
        }
        with _patch_paths(paths):
            stored = capture_quality_snapshots(
                board=board,
                candidates=[row],
                stage='opening_0920',
            )
        if stored:
            return _fail('radar-only candidate must not create snapshot')
        with _patch_paths(paths):
            if eligible_snapshots_for_session('2026-07-10'):
                return _fail('no eligible snapshots expected')
    return 0


def test_below_threshold_skipped() -> int:
    from backend.trading.candidate_outcome_learning import (
        capture_quality_snapshots,
        outcome_learning_skip_reason,
    )

    row = {'ticker': 'BEL', 'score': 55, 'state': 'TRADECARD_CANDIDATE'}
    if outcome_learning_skip_reason(row) != 'below_threshold':
        return _fail('score 55 must be below_threshold')

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = _paths(Path(tmpdir))
        board = {'session_date': '2026-07-10', 'scanner_freshness_status': 'CURRENT'}
        with _patch_paths(paths):
            stored = capture_quality_snapshots(
                board=board,
                candidates=[row],
                stage='final_0931',
            )
        if stored:
            return _fail('below-threshold candidate must not create snapshot')
    return 0


def test_stale_scanner_skipped() -> int:
    from backend.trading.candidate_outcome_learning import capture_quality_snapshots

    row = {'ticker': 'DIXON', 'score': 72, 'state': 'TRADECARD_CANDIDATE'}
    board = {
        'session_date': '2026-07-10',
        'quality_tradecard_blocked': True,
        'scanner_freshness_status': 'STALE',
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = _paths(Path(tmpdir))
        with _patch_paths(paths):
            stored = capture_quality_snapshots(
                board=board,
                candidates=[row],
                stage='manual_tradecards',
            )
        if stored:
            return _fail('stale scanner must not create snapshot')
    return 0


def test_quality_candidate_captured() -> int:
    from backend.trading.candidate_outcome_learning import capture_quality_snapshots

    row = {'ticker': 'BEL', 'score': 72, 'state': 'TRADECARD_CANDIDATE', 'why': ['volume']}
    board = {'session_date': '2026-07-10', 'scanner_freshness_status': 'CURRENT'}
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = _paths(Path(tmpdir))
        with _patch_paths(paths):
            stored = capture_quality_snapshots(
                board=board,
                candidates=[row],
                stage='opening_0920',
            )
        if not stored or stored[0].get('symbol') != 'BEL':
            return _fail('eligible quality candidate must create snapshot')
    return 0


def test_learn_today_no_stale_52i_wording() -> int:
    from backend.trading.candidate_outcome_learning import format_learn_today_telegram

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = _paths(Path(tmpdir))
        with _patch_paths(paths), patch(
            'backend.trading.candidate_outcome_learning._session_date',
            return_value='2026-07-10',
        ):
            text = format_learn_today_telegram(session_date='2026-07-10')
    if '52I' in text:
        return _fail('/learn today must not mention stale 52I wording')
    if 'No quality tradecard snapshots today.' not in text:
        return _fail('missing no quality snapshots message')
    if 'skipped_watch_only:' not in text:
        return _fail('missing skipped_watch_only counter')
    if 'auto-captured only from quality tradecards' not in text:
        return _fail('missing quality tradecards header')
    return 0


def test_tradecard_outcome_no_eligible() -> int:
    from backend.trading.tradecard_journal import format_tradecard_outcome_telegram

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = _paths(Path(tmpdir))
        with _patch_paths(paths), patch(
            'backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots',
            return_value=False,
        ):
            text = format_tradecard_outcome_telegram(session_date='2026-07-10')
    if 'No eligible tradecard outcome today.' not in text:
        return _fail('missing no eligible tradecard outcome message')
    if 'Radar/watch-only candidates are not outcome candidates.' not in text:
        return _fail('missing radar/watch-only note')
    return 0


def test_weekly_tradecard_signal_skipped_for_radar() -> int:
    from backend.trading.weekly_signal_capture import capture_tradecard_signals

    captured: list[dict] = []

    def _capture(**kwargs):
        captured.append(kwargs)

    row = {'ticker': 'BAJAJCON', 'score': 72, 'state': 'RADAR_ARMED'}
    board = {'scanner_freshness_status': 'CURRENT'}
    with patch('backend.trading.weekly_signal_capture._safe_capture', side_effect=_capture):
        capture_tradecard_signals([row], board=board)
    if captured:
        return _fail('weekly TRADECARD signal must not be written for radar-only row')
    return 0


def test_weekly_explain_bel_not_r() -> int:
    from backend.trading.screener_memory import resolve_screener_query
    from backend.trading.weekly_conviction_engine import _resolve_symbol_context, format_weekly_explain_telegram

    rows = [
        {
            'symbol_key': 'R',
            'symbol': 'R',
            'company_name': 'R R Kabel',
            'imported_at': '2026-07-10T10:00:00',
        },
        {
            'symbol_key': 'BEL',
            'symbol': 'BEL',
            'company_name': 'Bharat Electronics',
            'imported_at': '2026-07-09T10:00:00',
        },
    ]
    with patch('backend.trading.screener_memory._load_jsonl', return_value=rows), patch(
        'backend.trading.longterm_snapshot_memory.symbol_longterm_memory',
        return_value={'count': 0},
    ), patch(
        'backend.trading.weekly_conviction_engine.get_weekly_signal_events',
        return_value=[],
    ), patch(
        'backend.trading.weekly_conviction_engine._load_jsonl',
        return_value=[],
    ), patch(
        'backend.trading.weekly_conviction_engine._lookup_symbol_evaluation',
        return_value=None,
    ), patch(
        'backend.trading.screener_memory.summarize_symbol_screener',
        return_value={},
    ):
        if resolve_screener_query('BEL') is not None:
            sym = _normalize = __import__(
                'backend.trading.screener_memory', fromlist=['_normalize_symbol']
            )._normalize_symbol(resolve_screener_query('BEL').get('symbol_key'))
            if sym == 'R':
                return _fail('resolve_screener_query must not map BEL to R')
        sym, company, _ = _resolve_symbol_context('BEL')
        if sym != 'BEL':
            return _fail(f'BEL must resolve to BEL, got {sym!r}')
        if sym == 'R':
            return _fail('BEL must not resolve to R')
        text = format_weekly_explain_telegram('BEL')
    if 'WEEKLY EXPLAIN — R' in text:
        return _fail('/weekly explain BEL must not show R header')
    if 'WEEKLY EXPLAIN — BEL' not in text:
        return _fail('/weekly explain must show BEL header')
    if 'R R Kabel' in text and 'Bharat Electronics' not in text:
        return _fail('must not show R R Kabel for BEL query')
    return 0


def test_close_lines_separate_watchlist() -> int:
    from backend.analytics.actual_learning_resolver import format_actual_learning_close_lines

    summary = {
        'sample_updated': 2,
        'watchlist': {'win': 1, 'loss': 1, 'neutral': 0},
        'avoid': {'success': 0, 'fail': 0},
        'tradecard': {'resolved': 0, 'no_fill': 0},
        'explanation': {
            'best_signal_today': 'BAJAJCON +2.1%',
            'worst_signal_today': 'DIXON -1.4%',
        },
        'pending_data': 0,
        'pending_reasons': {},
    }
    with patch(
        'backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots',
        return_value=False,
    ):
        lines = format_actual_learning_close_lines(summary)
    text = '\n'.join(lines)
    if 'Tradecard outcome review:' in text:
        return _fail('actual learning close lines must not duplicate tradecard outcome review')
    if 'Watchlist accuracy only:' not in text:
        return _fail('close must label watchlist accuracy only')
    if 'Best watchlist signal:' not in text:
        return _fail('close must show best watchlist signal label')
    if 'Tradecard resolved/no-fill:' in text:
        return _fail('close must not show tradecard resolved when no eligible snapshots')
    return 0


def main() -> int:
    tests = (
        test_build_label_52o,
        test_radar_only_skipped,
        test_below_threshold_skipped,
        test_stale_scanner_skipped,
        test_quality_candidate_captured,
        test_learn_today_no_stale_52i_wording,
        test_tradecard_outcome_no_eligible,
        test_weekly_tradecard_signal_skipped_for_radar,
        test_weekly_explain_bel_not_r,
        test_close_lines_separate_watchlist,
    )
    for test in tests:
        err = test()
        if err:
            return err
        print(f'OK: {test.__name__}')
    print('POSTMARKET_NO_QUALITY_OUTCOME_52O_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
