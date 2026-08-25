#!/usr/bin/env python3
"""Validator — AstraEdge 52Q daily review learning truth (read-only)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'trading' / 'daily_learning_truth.py',
    PROJECT_ROOT / 'backend' / 'trading' / 'candidate_outcome_learning.py',
    PROJECT_ROOT / 'backend' / 'orchestration' / 'alert_quality_engine.py',
    PROJECT_ROOT / 'backend' / 'analytics' / 'actual_learning_resolver.py',
    PROJECT_ROOT / 'scripts' / 'test_daily_review_learning_truth_52q.py',
    PROJECT_ROOT / 'scripts' / 'validate_daily_review_learning_truth_52q.py',
)


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52Q_DAILY_REVIEW_LEARNING_TRUTH_FAIL: {msg}', file=sys.stderr)
    return 1


def _file_digest(path: Path) -> str:
    if not path.is_file():
        return 'missing'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    before = {str(p): _file_digest(p) for p in WATCHED_PATHS}

    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    # Exact identity pairs only — mismatched stage/Telegram combinations must fail.
    _allowed_build_pairs = {
        ('52Q', 'AstraEdge 52Q'),
        ('52R-A1', 'AstraEdge 52R-A1'),
        ('52R-A2', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-C1A'),
        ('52R-C1B', 'AstraEdge 52R-C1B'),
        ('52R-D', 'AstraEdge 52R-D'),
        ('52R-D2P', 'AstraEdge 52R-D2P'),
        ('52R-D2', 'AstraEdge 52R-D2'),
        ('53A', 'AstraEdge 53A'),
        ('53A2', 'AstraEdge 53A2'),
    }
    if (BUILD_STAGE, TELEGRAM_BUILD) not in _allowed_build_pairs:
        return _fail(
            f'build must be an exact 52Q-compatible pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )

    truth_src = (PROJECT_ROOT / 'backend/trading/daily_learning_truth.py').read_text(encoding='utf-8')
    for needle in (
        'reconcile_daily_learning_truth',
        'is_canonical_winner_reason_eligible',
        'Eligible learning samples added today',
        'Total eligible historical samples',
        'daily_added_provenance_available',
        'historical_total_available',
        'daily_provenance_inconsistent',
        'snapshot_id_mismatch',
    ):
        if needle not in truth_src:
            return _fail(f'daily_learning_truth missing {needle!r}')

    quality_src = (PROJECT_ROOT / 'backend/orchestration/alert_quality_engine.py').read_text(encoding='utf-8')
    if 'Actual learning sample updated:' in quality_src:
        return _fail('alert_quality_engine must not emit Actual learning sample updated')
    close_src = (PROJECT_ROOT / 'backend/analytics/actual_learning_resolver.py').read_text(encoding='utf-8')
    if 'Actual learning sample updated:' in close_src:
        return _fail('actual_learning_resolver close lines must not emit Actual learning sample updated')

    # Validator must never write/promote build files.
    validator_src = Path(__file__).read_text(encoding='utf-8')
    promote_needle = 'def ' + '_promote_build'
    write_needle = '.' + 'write_text('
    if promote_needle in validator_src or write_needle in validator_src:
        return _fail('52Q validator must remain strictly read-only')

    import os

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_daily_review_learning_truth_52q.py')],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        env=env,
    )
    out = (proc.stdout or '') + '\n' + (proc.stderr or '')
    if proc.returncode != 0 or 'DAILY_REVIEW_LEARNING_TRUTH_52Q_PASS' not in out:
        print(out[-5000:], file=sys.stderr)
        return _fail('focused 52Q learning-truth test did not pass')

    mandatory_pass_markers = (
        'PASS: test_build_is_exactly_52q',
        'PASS: test_nilkamal_captured_only_not_winner',
        'PASS: test_valid_matching_snapshot_and_win_accepted',
        'PASS: test_unreadable_learning_store_daily_and_total_unavailable',
        'PASS: test_valid_zero_plus_malformed_marker_unavailable',
        'PASS: test_fractional_inserted_marker_unavailable',
        'PASS: test_distinct_resolve_ids_claiming_same_sample_unavailable',
        'PASS: test_same_session_missing_recorded_at_zero_marker_unavailable',
        'DAILY_REVIEW_LEARNING_TRUTH_52Q_PASS',
    )
    for marker in mandatory_pass_markers:
        if marker not in out:
            return _fail(f'focused output missing mandatory marker {marker!r}')

    after = {str(p): _file_digest(p) for p in WATCHED_PATHS}
    if before != after:
        changed = [p for p in before if before[p] != after.get(p)]
        return _fail(f'validator mutated watched source files: {changed}')

    print('ASTRAEDGE_PHASE_52Q_DAILY_REVIEW_LEARNING_TRUTH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
