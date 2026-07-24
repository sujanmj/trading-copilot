#!/usr/bin/env python3
"""AstraEdge 52O-B — market memory legacy outcome label polish."""

from __future__ import annotations

import json
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
    print(f'MARKET_MEMORY_LEGACY_LABEL_52OB_FAIL: {msg}', file=sys.stderr)
    return 1


def _memory_dashboard_with_stylamind() -> dict:
    return {
        'ok': True,
        'stats': {'predictions': 12, 'outcomes': 4},
        'learning': {'overall': {'total_predictions': 12, 'wins': 3, 'losses': 1}},
        'latest_outcomes': [
            {
                'ticker': 'STYLAMIND',
                'resolved_as': 'NO_FILL',
                'actual_move': 0.0,
            }
        ],
    }


def _patch_memory_paths(tmp: Path):
    cache_file = tmp / 'market_memory_dashboard_cache.json'
    cache_file.write_text(json.dumps(_memory_dashboard_with_stylamind()), encoding='utf-8')
    return patch('backend.telegram.lazy_command_runner.MEMORY_CACHE_FILE', cache_file)


def test_build_label_52o() -> int:
    from scripts.test_build_helpers import assert_canonical_build, expected_build_label

    err = assert_canonical_build(_fail)
    if err:
        return err
    if not expected_build_label().startswith('AstraEdge 52'):
        return _fail(f'unexpected build label {expected_build_label()!r}')
    return 0


def test_legacy_header_when_no_eligible_snapshots() -> int:
    from backend.trading.candidate_outcome_learning import format_market_memory_latest_outcomes_header

    with patch(
        'backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots',
        return_value=False,
    ):
        lines = format_market_memory_latest_outcomes_header()
    text = '\n'.join(lines)
    if 'Latest reference outcomes:' not in text:
        return _fail('expected Latest reference outcomes header')
    if 'not used for candidate outcome learning' not in text:
        return _fail('expected not-used-for-learning subtitle')
    if 'Latest tradecard outcomes:' in text:
        return _fail('must not use tradecard outcomes header without eligible snapshots')
    return 0


def test_memory_close_labels_reference_not_quality_learning() -> int:
    from backend.telegram.lazy_command_runner import run_memory_only

    with tempfile.TemporaryDirectory() as tmpdir:
        with _patch_memory_paths(Path(tmpdir)), patch(
            'backend.analytics.unified_decision_engine.get_calibration_mode',
            return_value='ready',
        ), patch(
            'backend.storage.outcome_resolver.get_canonical_outcome_stats',
            return_value={
                'predictions_tracked': 12,
                'resolved_total': 4,
                'pending_total': 2,
                'hit_rate': 0.5,
                'bullish_hit_rate': 0.6,
                'bearish_hit_rate': 0.4,
                'neutral': 1,
                'last_resolved_at': '2026-07-10',
            },
        ), patch(
            'backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots',
            return_value=False,
        ), patch(
            'backend.trading.macro_shock_sentinel.format_macro_memory_snippet',
            return_value=[],
        ):
            text = str(run_memory_only().get('text') or '')

    if 'Latest reference outcomes:' not in text:
        return _fail('/memory must label latest outcomes as reference when no eligible snapshots')
    if 'Latest tradecard outcomes:' in text:
        return _fail('must not label as tradecard outcomes without eligible snapshots')
    if 'not used for candidate outcome learning' not in text:
        return _fail('missing not-used-for-learning subtitle')
    if 'STYLAMIND — NO_FILL' not in text:
        return _fail('reference outcome row should still display')
    if text.count('Latest reference outcomes:') != 1:
        return _fail('reference outcomes header must appear once')
    return 0


def test_quality_header_when_eligible_outcomes_exist() -> int:
    from backend.trading.candidate_outcome_learning import format_market_memory_latest_outcomes_header

    with patch(
        'backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots',
        return_value=True,
    ), patch(
        'backend.trading.candidate_outcome_learning.candidate_outcomes_count_for_session',
        return_value=2,
    ):
        lines = format_market_memory_latest_outcomes_header()
    text = '\n'.join(lines)
    if 'Latest tradecard outcomes:' not in text:
        return _fail('expected Latest tradecard outcomes header when eligible outcomes exist')
    if 'not used for candidate outcome learning' in text:
        return _fail('quality header must not include legacy subtitle')
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
        test_legacy_header_when_no_eligible_snapshots,
        test_memory_close_labels_reference_not_quality_learning,
        test_quality_header_when_eligible_outcomes_exist,
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
        print(f'MARKET_MEMORY_LEGACY_LABEL_52OB_FAIL: {failed} test(s) failed', file=sys.stderr)
        return 1
    print('MARKET_MEMORY_LEGACY_LABEL_52OB_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
