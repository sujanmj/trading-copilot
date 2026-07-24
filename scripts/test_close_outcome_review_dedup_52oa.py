#!/usr/bin/env python3
"""AstraEdge 52O-A — /close tradecard outcome review de-duplication."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'CLOSE_OUTCOME_REVIEW_DEDUP_52OA_FAIL: {msg}', file=sys.stderr)
    return 1


def _learning_summary() -> dict:
    return {
        'sample_updated': 1,
        'watchlist': {'win': 1, 'loss': 0, 'neutral': 1},
        'avoid': {'success': 0, 'fail': 0},
        'tradecard': {'resolved': 0, 'no_fill': 1},
        'pending_data': 0,
        'pending_reasons': {},
        'explanation': {
            'best_signal_today': 'BAJAJCON +2.1%',
            'worst_signal_today': 'DIXON -1.4%',
            'trust_tomorrow': 'Fresh scanner confirmation.',
            'reduce_tomorrow': 'Stale setups.',
        },
    }


def _build_close_text() -> str:
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text

    tradecard_review = '\n'.join([
        '<b>Tradecard outcome review:</b>',
        'No eligible quality tradecard snapshots today.',
        'Radar/watchlist candidates were reference-only and not scored as tradecard wins/losses.',
    ])
    with patch('backend.telegram.india_mode_lock.is_premarket_phase', return_value=False), \
         patch('backend.telegram.india_mode_lock.resolve_telegram_market_phase', return_value='INDIA_AFTER_HOURS'), \
         patch('backend.telegram.india_mode_lock.is_live_market_hours_phase', return_value=False), \
         patch('backend.telegram.telegram_brief_scheduler._postmarket_close_pack_lines', return_value=(
             ['Report: fresh · 0m', ''],
             False,
             {'fresh': True, 'freshness_meta': {'lines': {'report': 'Report: fresh · 0m'}}},
         )), \
         patch('backend.trading.tradecard_journal.resolve_close_pending_tradecards', return_value={'updated': 0}), \
         patch('backend.trading.tradecard_journal.format_tradecard_review_section', return_value=tradecard_review), \
         patch('backend.trading.tradecard_journal.summarize_today_outcomes', return_value={
             'counts': {'generated': 1, 'no_fill': 1, 'pending': 0, 'filled': 0},
             'best': [],
             'worst': [],
         }), \
         patch('backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots', return_value=False), \
         patch('backend.analytics.actual_learning_resolver.run_actual_learning_resolver', return_value=_learning_summary()), \
         patch('backend.telegram.lazy_command_runner.run_memory_only', return_value={'text': 'memory'}), \
         patch('backend.telegram.lazy_command_runner.run_market_only', return_value={'text': '<b>Market payload</b>'}), \
         patch('backend.telegram.telegram_brief_scheduler._build_today_tomorrow_text', return_value='tomorrow'):
        return build_close_brief_text()


def test_build_label_52o() -> int:
    from scripts.test_build_helpers import assert_canonical_build, expected_build_label

    err = assert_canonical_build(_fail)
    if err:
        return err
    if not expected_build_label().startswith('AstraEdge 52'):
        return _fail(f'unexpected build label {expected_build_label()!r}')
    return 0


def test_close_tradecard_outcome_review_once() -> int:
    text = _build_close_text()
    count = text.count('Tradecard outcome review:')
    if count != 1:
        return _fail(f'expected Tradecard outcome review once, got {count}')
    if text.count('No eligible quality tradecard snapshots today.') != 1:
        return _fail('expected single no-eligible snapshots line')
    return 0


def test_close_no_fake_tradecard_wl() -> int:
    text = _build_close_text()
    for needle in ('Best: ', 'Worst: ', 'won:', 'lost:', 'Tradecard resolved/no-fill:'):
        if needle in text:
            return _fail(f'no-eligible close must not show tradecard W/L framing: {needle!r}')
    if 'Tradecard resolution: no fill' in text:
        return _fail('no-eligible close must not show tradecard resolution summary')
    return 0


def test_close_legacy_journal_labelled() -> int:
    text = _build_close_text()
    for needle in (
        'Legacy/reference tradecard journal:',
        'No-fill/reference records: 1',
        'Not used for candidate outcome learning.',
    ):
        if needle not in text:
            return _fail(f'missing legacy journal line: {needle!r}')
    return 0


def test_close_watchlist_accuracy_separate() -> int:
    text = _build_close_text()
    if 'Watchlist accuracy only:' not in text:
        return _fail('close must keep watchlist accuracy section')
    if 'Best watchlist signal: BAJAJCON +2.1%' not in text:
        return _fail('close must show best watchlist signal separately')
    if 'Worst watchlist signal: DIXON -1.4%' not in text:
        return _fail('close must show worst watchlist signal separately')
    return 0


def test_qa_smoke_pass() -> int:
    from backend.qa.qa_runner import format_qa_result, run_qa_smoke

    result = run_qa_smoke()
    text = format_qa_result(result)
    if 'QA SMOKE — PASS' not in text:
        return _fail(f'QA smoke must PASS, got {text.splitlines()[0]!r}')
    return 0


def main() -> int:
    tests = (
        test_build_label_52o,
        test_close_tradecard_outcome_review_once,
        test_close_no_fake_tradecard_wl,
        test_close_legacy_journal_labelled,
        test_close_watchlist_accuracy_separate,
        test_qa_smoke_pass,
    )
    failed = 0
    for test in tests:
        rc = test()
        if rc:
            failed += 1
        else:
            print(f'PASS: {test.__name__}')
    if failed:
        print(f'CLOSE_OUTCOME_REVIEW_DEDUP_52OA_FAIL: {failed} test(s) failed', file=sys.stderr)
        return 1
    print('CLOSE_OUTCOME_REVIEW_DEDUP_52OA_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
