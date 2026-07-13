#!/usr/bin/env python3
"""AstraEdge 52O-C — daily review outcome review de-duplication + skip polish."""

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
    print(f'DAILY_REVIEW_OUTCOME_DEDUP_52OC_FAIL: {msg}', file=sys.stderr)
    return 1


def _opening() -> dict:
    return {
        'radar_armed': 2,
        'opening_radar': 0,
        'early_tradecards_generated': 1,
        'final_confirmation_generated': 1,
        'early_tradecard_best': 'SFL',
        'final_confirmation_best': 'BALRAMCHIN',
        'final_confirmation_state': 'WATCH_ONLY',
        'final_best_score': 23,
        'confirmed': 0,
        'rejected': 0,
        'wait_pullback': 1,
        'pullback_only': 0,
        'early_candidates': [
            {'ticker': 'SFL', 'score': 41, 'rank': 1, 'state': 'LOW_CONFIDENCE'},
            {'ticker': 'BALRAMCHIN', 'score': 23, 'rank': 2, 'state': 'WATCH_ONLY'},
        ],
    }


def _learning_summary() -> dict:
    return {
        'sample_updated': 0,
        'watchlist': {'win': 0, 'loss': 0, 'neutral': 0},
        'avoid': {'success': 0, 'fail': 0},
        'tradecard': {'resolved': 0, 'no_fill': 1},
        'pending_data': 0,
        'pending_reasons': {},
    }


def _quality_lines() -> list[str]:
    from backend.orchestration.alert_quality_engine import format_daily_review_quality_lines

    with patch(
        'backend.orchestration.alert_quality_engine.daily_review_quality_buckets',
        return_value={
            'research_watchlist_sent': 1,
            'live_confirmed_setups': 0,
            'rejected_setups': 0,
            'missed_opportunities': 0,
            'tradecards_generated': 1,
            'tradecards_filled': 0,
            'tradecards_resolved': 0,
            'tradecard_wins': 0,
            'tradecard_losses': 0,
            'tradecard_neutral': 1,
            'tradecard_pending': 0,
            'learning_sample_updated': 0,
            'watchlist_win': 0,
            'watchlist_loss': 0,
            'watchlist_neutral': 0,
            'avoid_success': 0,
            'avoid_fail': 0,
            'tradecard_actual_resolved': 0,
            'tradecard_actual_no_fill': 1,
            'pending_data': 0,
            'pending_reasons': {},
            'opening_workflow': _opening(),
        },
    ), patch(
        'backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots',
        return_value=False,
    ), patch(
        'backend.trading.candidate_outcome_learning.eligible_learning_symbols',
        return_value=[],
    ), patch(
        'backend.trading.candidate_outcome_learning.skip_stats_for_session',
        return_value={'watch_only': 0, 'below_threshold': 0, 'stale_scanner': 0},
    ):
        return format_daily_review_quality_lines(
            tradecard_counts={'generated': 1, 'filled': 0, 'no_fill': 1, 'pending': 0},
            actual_learning_summary=_learning_summary(),
        )


def _daily_review_text() -> str:
    from backend.analytics.eod_outcome_scoring import format_eod_telegram_message

    quality = _quality_lines()
    with patch(
        'backend.analytics.eod_outcome_scoring.format_daily_review_alert_lines',
        return_value=['Premarket watch: 0 · Live watch: 0 · Open setups: 0 · Intraday alerts: 2'],
    ), patch(
        'backend.orchestration.alert_quality_engine.format_daily_review_quality_lines',
        return_value=quality,
    ), patch(
        'backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots',
        return_value=False,
    ), patch(
        'backend.trading.candidate_outcome_learning.format_candidate_outcome_learning_block',
        return_value=[
            'No quality tradecard snapshots today.',
            'Reason:',
            'Outcome learning:',
            'won: 0',
        ],
    ), patch(
        'backend.trading.tradecard_journal.format_tradecard_review_section',
        return_value='\n'.join([
            '<b>Tradecard outcome review:</b>',
            'No eligible quality tradecard snapshots today.',
            'Radar/watchlist candidates were reference-only and not scored as tradecard wins/losses.',
        ]),
    ):
        return format_eod_telegram_message(
            {
                'date': '2026-07-13',
                'data_available': True,
                'alerts_sent': 2,
                'resolved': 0,
                'wins': 0,
                'losses': 0,
                'neutrals': 0,
                'partials': 0,
                'best': [],
                'worst': [],
                'by_alert_type': {},
                'premarket_confirmed': 0,
                'premarket_rejected': 0,
                'emergency_useful': 0,
                'emergency_duplicate_skipped': 0,
                'alert_tracking': {
                    'premarket_watch_count': 0,
                    'live_watch_count': 0,
                    'open_setup_count': 0,
                    'intraday_alert_count': 2,
                    'pending_review_count': 2,
                    'confirmed_count': 0,
                    'rejected_count': 0,
                    'wait_volume_count': 0,
                    'entry_missed_count': 0,
                },
            },
            pending_meta={'pending_active': 0, 'expired': 0},
        )


def test_build_label_52o() -> int:
    from scripts.test_build_helpers import assert_canonical_build, expected_build_label

    err = assert_canonical_build(_fail)
    if err:
        return err
    if expected_build_label() != 'AstraEdge 52O':
        return _fail(f'expected AstraEdge 52O, got {expected_build_label()!r}')
    return 0


def test_daily_review_outcome_review_once() -> int:
    text = _daily_review_text()
    count = text.count('Tradecard outcome review:')
    if count != 1:
        return _fail(f'expected Tradecard outcome review once, got {count}')
    if text.count('No eligible quality tradecard snapshots today.') != 1:
        return _fail('expected single no-eligible snapshots line')
    if 'No quality tradecard snapshots today.' in text:
        return _fail('must not duplicate No quality tradecard snapshots today block')
    return 0


def test_no_fake_wl_and_legacy_journal() -> int:
    text = '\n'.join(_quality_lines())
    if 'Tradecard resolved/no-fill:' in text:
        return _fail('no-eligible day must not show Tradecard resolved/no-fill')
    if 'Legacy/reference tradecard journal:' not in text:
        return _fail('missing legacy/reference tradecard journal label')
    if 'No-fill/reference records: 1' not in text:
        return _fail('missing no-fill/reference record count')
    if 'Not used for candidate outcome learning.' not in text:
        return _fail('missing not-used-for-learning label')
    for needle in ('Best: ', 'Worst: ', 'won: 1', 'lost: 1'):
        if needle in text and needle.startswith(('Best', 'Worst')):
            return _fail(f'no-eligible day must not show fake tradecard W/L: {needle!r}')
    if 'won: 0' not in text or 'lost: 0' not in text:
        return _fail('outcome learning counters should show zeros, not fake wins')
    return 0


def test_opening_workflow_labels() -> int:
    text = '\n'.join(_quality_lines())
    for needle in (
        'Early tradecard checks run: 1',
        'Final confirmation checks run: 1',
        'Early tradecard best: SFL — below quality threshold',
        'Final confirmation best: BALRAMCHIN — watch only / below threshold',
    ):
        if needle not in text:
            return _fail(f'missing opening workflow label: {needle!r}')
    if 'Early tradecards generated:' in text:
        return _fail('must not imply quality tradecard generated wording')
    if 'Learning candidate captured:' in text:
        return _fail('must not say Learning candidate captured when no eligible snapshots')
    return 0


def test_skip_counters_not_misleading_zero() -> int:
    text = '\n'.join(_quality_lines())
    if 'skipped_watch_only: 0' in text and 'skipped_below_threshold: 0' in text:
        return _fail('skip counters must not be misleading all-zero when watch-only/below-threshold exist')
    if 'skipped_watch_only:' not in text or 'skipped_below_threshold:' not in text:
        return _fail('missing skip counter lines')
    # Derived counts or availability label are both acceptable.
    watch_ok = (
        'skipped_watch_only: available in daily review only' in text
        or any(
            line.startswith('skipped_watch_only: ') and not line.endswith(': 0')
            for line in text.splitlines()
        )
    )
    below_ok = (
        'skipped_below_threshold: available in daily review only' in text
        or any(
            line.startswith('skipped_below_threshold: ') and not line.endswith(': 0')
            for line in text.splitlines()
        )
    )
    if not watch_ok or not below_ok:
        return _fail(f'skip counters still look empty/misleading:\n{text}')
    return 0


def test_close_52oa_unchanged() -> int:
    from scripts.test_close_outcome_review_dedup_52oa import (
        test_close_legacy_journal_labelled,
        test_close_tradecard_outcome_review_once,
        test_close_watchlist_accuracy_separate,
    )

    for test in (
        test_close_tradecard_outcome_review_once,
        test_close_legacy_journal_labelled,
        test_close_watchlist_accuracy_separate,
    ):
        rc = test()
        if rc:
            return _fail(f'/close 52O-A regression failed in {test.__name__}')
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
        test_daily_review_outcome_review_once,
        test_no_fake_wl_and_legacy_journal,
        test_opening_workflow_labels,
        test_skip_counters_not_misleading_zero,
        test_close_52oa_unchanged,
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
        print(f'DAILY_REVIEW_OUTCOME_DEDUP_52OC_FAIL: {failed} test(s) failed', file=sys.stderr)
        return 1
    print('DAILY_REVIEW_OUTCOME_DEDUP_52OC_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
