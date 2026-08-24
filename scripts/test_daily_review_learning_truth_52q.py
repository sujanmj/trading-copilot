#!/usr/bin/env python3
"""AstraEdge 52Q — daily review learning truth (pre-commit truth-safety)."""

from __future__ import annotations

import hashlib
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

DAY = '2099-07-28'
DAY_B = '2099-07-29'


def _fail(msg: str) -> int:
    print(f'DAILY_REVIEW_LEARNING_TRUTH_52Q_FAIL: {msg}', file=sys.stderr)
    return 1


def _quality_snap(**extra) -> dict:
    row = {
        'snapshot_id': 'snap-quality-1',
        'session_date': DAY,
        'stage': 'opening_0920',
        'symbol': 'WINCO',
        'score': 78,
        'state': 'TRADECARD_CANDIDATE',
        'reason_text': 'scanner confirmed + volume ignition',
        'reason_tags': ['fresh_scanner_confirmed', 'volume_above_2x'],
        'has_catalyst': True,
        'volume_participation': 3.1,
    }
    row.update(extra)
    return row


def _win_outcome(**extra) -> dict:
    row = {
        **_quality_snap(),
        'outcome': 'WIN',
        'reason_summary': 'fresh scanner + volume followthrough',
        'reason_tags': ['fresh_scanner_confirmed', 'volume_above_2x'],
        'resolved_at': f'{DAY}T15:45:00+05:30',
    }
    row.update(extra)
    return row


def _learning_row(*, symbol: str, session_date: str, outcome: str = 'WIN', **extra) -> dict:
    row = {
        'aggregate_key': f'{symbol}|cat|ok|GREEN|breakout',
        'sample_id': f'sid-{symbol}-{session_date}',
        'snapshot_id': extra.pop('snapshot_id', f'snap-{symbol}-{session_date}'),
        'symbol': symbol,
        'outcome': outcome,
        'session_date': session_date,
        'recorded_at': f'{session_date}T16:00:00+05:30',
        'stage': 'opening_0920',
        'state': 'TRADECARD_CANDIDATE',
        'score': 70,
        'reason_tags': ['fresh_scanner_confirmed'],
    }
    row.update(extra)
    return row


def _resolve_marker(
    *,
    inserted: int = 0,
    deduplicated: int = 0,
    session_date: str = DAY,
    resolve_id: str | None = None,
    sample_ids: list[str] | None = None,
    legacy: bool = False,
) -> dict:
    row = {
        'event': 'resolve_complete',
        'session_date': session_date,
        'inserted': inserted,
        'deduplicated': deduplicated,
        'sample_ids': list(sample_ids or []),
        'provenance_complete': True,
        'recorded_at': f'{session_date}T16:01:00+05:30',
    }
    if not legacy:
        row['resolve_id'] = resolve_id or f'resolve-{session_date}-{inserted}-{len(row["sample_ids"])}'
    return row


def _insert_event(*, sample_id: str, symbol: str, dedupe_key: str, session_date: str = DAY) -> dict:
    return {
        'event': 'learning_sample_mutation',
        'action': 'inserted',
        'sample_id': sample_id,
        'symbol': symbol,
        'session_date': session_date,
        'dedupe_key': dedupe_key,
    }


def test_build_is_exactly_52q() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    # Exact identity pairs only — mismatched stage/Telegram combinations must fail.
    allowed_build_pairs = {
        ('52Q', 'AstraEdge 52Q'),
        ('52R-A1', 'AstraEdge 52R-A1'),
        ('52R-A2', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2'),
    }
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed_build_pairs:
        return _fail(
            f'expected AstraEdge 52Q or compatible exact successor pair, '
            f'got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    return 0


def test_build_pair_mismatches_rejected_52q() -> int:
    """Mismatched stage/Telegram pairs must never be accepted by 52Q allowlist."""
    allowed_build_pairs = {
        ('52Q', 'AstraEdge 52Q'),
        ('52R-A1', 'AstraEdge 52R-A1'),
        ('52R-A2', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2'),
    }
    mismatches = (
        ('52Q', 'AstraEdge 52R-A1'),
        ('52R-A1', 'AstraEdge 52Q'),
        ('52P', 'AstraEdge 52Q'),
        ('52R-A2', 'AstraEdge 52R-A1'),
        ('52R-A1', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-A2'),
        ('52R-A2', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B1'),
        ('52R-B1', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2N'),
        ('52R-B2N', 'AstraEdge 52R-B2'),
    )
    for stage, telegram in mismatches:
        if (stage, telegram) in allowed_build_pairs:
            return _fail(f'mismatch pair must be rejected: {stage!r} / {telegram!r}')
    return 0


def test_nilkamal_captured_only_not_winner() -> int:
    from backend.trading.daily_learning_truth import (
        format_daily_learning_truth_lines,
        reconcile_daily_learning_truth,
    )

    observed = [{
        'ticker': 'NILKAMAL',
        'score': 71,
        'state': 'RADAR_ARMED',
        'why': ['scanner confirmed', 'catalyst match'],
        'has_catalyst': True,
    }]
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
        observed_candidates=observed,
    )
    if truth['canonical_outcomes_recorded_count'] != 0:
        return _fail('captured-only must not count canonical outcomes')
    if truth['eligible_learning_samples_added_today'] != 0:
        return _fail('captured-only must not increment daily-added samples')
    if any(w.get('symbol') == 'NILKAMAL' for w in truth['winner_reasons']):
        return _fail('NILKAMAL must not appear under Winner reasons')
    if not any(q.get('symbol') == 'NILKAMAL' for q in truth['qualification_reasons']):
        return _fail('NILKAMAL should appear under Candidate qualification reasons')
    text = '\n'.join(format_daily_learning_truth_lines(truth))
    winner_body = text.split('Winner reasons:')[-1]
    if 'NILKAMAL' in winner_body:
        return _fail('rendered Winner reasons must not include NILKAMAL')
    return 0


def test_outcome_only_win_without_persisted_snapshot_rejected() -> int:
    from backend.trading.daily_learning_truth import is_canonical_winner_reason_eligible

    outcome = _win_outcome()  # contains copied score/stage/snapshot_id
    ok, code = is_canonical_winner_reason_eligible(outcome, snapshot=None, session_date=DAY)
    if ok or code != 'no_quality_tradecard':
        return _fail(f'outcome-only WIN must be rejected no_quality_tradecard, got {ok}/{code}')
    return 0


def test_snapshot_outcome_ticker_mismatch_rejected() -> int:
    from backend.trading.daily_learning_truth import is_canonical_winner_reason_eligible

    snap = _quality_snap(symbol='AAA')
    outcome = _win_outcome(symbol='BBB', snapshot_id=snap['snapshot_id'])
    ok, code = is_canonical_winner_reason_eligible(outcome, snapshot=snap, session_date=DAY)
    if ok or code != 'ticker_mismatch':
        return _fail(f'expected ticker_mismatch, got {ok}/{code}')
    return 0


def test_snapshot_id_mismatch_rejected() -> int:
    from backend.trading.daily_learning_truth import is_canonical_winner_reason_eligible

    snap = _quality_snap(snapshot_id='snap-a')
    outcome = _win_outcome(snapshot_id='snap-b')
    ok, code = is_canonical_winner_reason_eligible(outcome, snapshot=snap, session_date=DAY)
    if ok or code != 'snapshot_id_mismatch':
        return _fail(f'expected snapshot_id_mismatch, got {ok}/{code}')
    return 0


def test_snapshot_session_mismatch_rejected() -> int:
    from backend.trading.daily_learning_truth import is_canonical_winner_reason_eligible

    snap = _quality_snap(session_date=DAY_B)
    outcome = _win_outcome(session_date=DAY)
    ok, code = is_canonical_winner_reason_eligible(outcome, snapshot=snap, session_date=DAY)
    if ok or code != 'session_mismatch':
        return _fail(f'expected session_mismatch for snapshot, got {ok}/{code}')
    return 0


def test_outcome_session_mismatch_rejected() -> int:
    from backend.trading.daily_learning_truth import is_canonical_winner_reason_eligible

    snap = _quality_snap(session_date=DAY)
    outcome = _win_outcome(session_date=DAY_B)
    ok, code = is_canonical_winner_reason_eligible(outcome, snapshot=snap, session_date=DAY)
    if ok or code != 'session_mismatch':
        return _fail(f'expected session_mismatch for outcome, got {ok}/{code}')
    return 0


def test_valid_matching_snapshot_and_win_accepted() -> int:
    from backend.trading.daily_learning_truth import (
        is_canonical_winner_reason_eligible,
        reconcile_daily_learning_truth,
    )

    snap = _quality_snap()
    outcome = _win_outcome()
    ok, code = is_canonical_winner_reason_eligible(outcome, snapshot=snap, session_date=DAY)
    if not ok or code != 'ok':
        return _fail(f'valid pair must be accepted, got {ok}/{code}')
    learning = [_learning_row(symbol='WINCO', session_date=DAY, snapshot_id=snap['snapshot_id'])]
    from backend.trading.daily_learning_truth import learning_record_dedupe_key

    key = learning_record_dedupe_key(learning[0])
    sid = learning[0]['sample_id']
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[snap],
        outcomes=[outcome],
        learning_records=learning,
        mutations=[
            _insert_event(sample_id=sid, symbol='WINCO', dedupe_key=key),
            _resolve_marker(inserted=1, sample_ids=[sid], resolve_id='pass-winco'),
        ],
    )
    if not any(w.get('symbol') == 'WINCO' for w in truth['winner_reasons']):
        return _fail('canonical WIN with matching snapshot must appear under Winner reasons')
    if truth['eligible_learning_samples_added_today'] != 1:
        return _fail(f'expected daily added 1, got {truth["eligible_learning_samples_added_today"]}')
    return 0


def test_canonical_lost_not_winner() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    snap = _quality_snap(symbol='LOSSCO', snapshot_id='snap-loss')
    outcome = _win_outcome(symbol='LOSSCO', snapshot_id='snap-loss', outcome='LOSS')
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[snap],
        outcomes=[outcome],
        learning_records=[_learning_row(symbol='LOSSCO', session_date=DAY, outcome='LOSS', snapshot_id='snap-loss')],
        mutations=[_resolve_marker(inserted=0)],
    )
    if any(w.get('symbol') == 'LOSSCO' for w in truth['winner_reasons']):
        return _fail('LOSS must not appear under Winner reasons')
    if truth['canonical_outcomes_recorded_count'] != 1:
        return _fail('LOSS still counts as canonical outcome')
    return 0


def test_unresolved_quality_not_winner_or_sample() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    snap = _quality_snap(symbol='PENDCO', snapshot_id='snap-pend')
    outcome = {**snap, 'outcome': 'PENDING_DATA'}
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[snap],
        outcomes=[outcome],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
    )
    if any(w.get('symbol') == 'PENDCO' for w in truth['winner_reasons']):
        return _fail('unresolved must not be winner')
    if truth['eligible_learning_samples_added_today'] != 0:
        return _fail('unresolved must not count as completed learning sample')
    if truth['canonical_outcomes_recorded_count'] != 0:
        return _fail('pending must not count as recorded canonical outcome')
    return 0


def test_watch_only_pullback_excluded() -> int:
    from backend.trading.daily_learning_truth import is_canonical_winner_reason_eligible

    snap = _quality_snap(symbol='PVRINOX', snapshot_id='snap-pvr', state='PULLBACK_ONLY_PLAN', score=80)
    outcome = {**snap, 'outcome': 'WIN'}
    ok, code = is_canonical_winner_reason_eligible(outcome, snapshot=snap, session_date=DAY)
    if ok or code != 'watch_only':
        return _fail(f'pullback-only must fail with watch_only, got {ok}/{code}')
    return 0


def test_reference_only_excluded() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    snap = _quality_snap(symbol='REFCO', snapshot_id='snap-ref')
    outcome = _win_outcome(symbol='REFCO', snapshot_id='snap-ref', reference_only=True)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[snap],
        outcomes=[outcome],
        learning_records=[{
            **_learning_row(symbol='REFCO', session_date=DAY, snapshot_id='snap-ref'),
            'reference_only': True,
        }],
        mutations=[_resolve_marker(inserted=0)],
    )
    if any(w.get('symbol') == 'REFCO' for w in truth['winner_reasons']):
        return _fail('reference-only must not appear under Winner reasons')
    if truth['eligible_learning_samples_total'] != 0:
        return _fail('reference-only excluded from historical learning total')
    return 0


def test_orphan_insert_event_does_not_count() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            {
                'event': 'learning_sample_mutation',
                'action': 'inserted',
                'sample_id': 'orphan',
                'symbol': 'ORPH',
                'session_date': DAY,
                'dedupe_key': 'orphan-key',
            },
            _resolve_marker(inserted=1, sample_ids=['orphan'], resolve_id='pass-orphan'),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('orphan insert vs marker=1 must be inconsistent/unavailable')
    if truth['eligible_learning_samples_added_today'] is not None:
        return _fail('orphan insert must not set daily-added count')
    if 'daily_provenance_inconsistent' not in truth['reason_codes']:
        return _fail('expected daily_provenance_inconsistent')
    return 0


def test_marker_says_one_without_persisted_record_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[_resolve_marker(inserted=1, sample_ids=['missing-sid'], resolve_id='pass-missing')],
    )
    if truth['daily_added_provenance_available'] or truth['eligible_learning_samples_added_today'] is not None:
        return _fail('marker without persisted match must be unavailable')
    return 0


def test_matching_event_record_and_marker_count_once() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    learning = [_learning_row(symbol='NEWCO', session_date=DAY)]
    key = learning_record_dedupe_key(learning[0])
    sid = learning[0]['sample_id']
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=learning,
        mutations=[
            _insert_event(sample_id=sid, symbol='NEWCO', dedupe_key=key),
            _resolve_marker(inserted=1, sample_ids=[sid], resolve_id='pass-newco'),
        ],
    )
    if truth['eligible_learning_samples_added_today'] != 1:
        return _fail(f'expected daily added 1, got {truth}')
    return 0


def test_duplicate_insert_events_count_once() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    row = _learning_row(symbol='DUPCO', session_date=DAY)
    key = learning_record_dedupe_key(row)
    sid = row['sample_id']
    ev = _insert_event(sample_id=sid, symbol='DUPCO', dedupe_key=key)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row, dict(row)],
        mutations=[ev, dict(ev), _resolve_marker(inserted=1, sample_ids=[sid], resolve_id='pass-dup')],
    )
    if truth['eligible_learning_samples_added_today'] != 1:
        return _fail(f'duplicate inserts must count once, got {truth}')
    if truth['eligible_learning_samples_total'] != 1:
        return _fail(f'total must dedupe, got {truth}')
    return 0


def test_wrong_event_type_provenance_complete_does_not_prove_zero() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[{
            'event': 'not_resolve_complete',
            'provenance_complete': True,
            'session_date': DAY,
            'inserted': 0,
            'deduplicated': 0,
        }],
    )
    if truth['daily_added_provenance_available']:
        return _fail('wrong event type must not prove daily provenance')
    if truth['eligible_learning_samples_added_today'] is not None:
        return _fail('wrong event type must leave daily-added null')
    return 0


def test_malformed_inserted_marker_does_not_prove_count() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    for bad in ('bad', ['1'], {'n': 1}, None):
        truth = reconcile_daily_learning_truth(
            session_date=DAY,
            snapshots=[],
            outcomes=[],
            learning_records=[],
            mutations=[{
                'event': 'resolve_complete',
                'provenance_complete': True,
                'session_date': DAY,
                'inserted': bad,
                'deduplicated': 0,
            }],
        )
        if truth['daily_added_provenance_available']:
            return _fail(f'malformed inserted={bad!r} must not prove provenance')
    return 0


def test_duplicate_resolve_markers_do_not_inflate() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    row = _learning_row(symbol='ONCE', session_date=DAY)
    key = learning_record_dedupe_key(row)
    sid = row['sample_id']
    marker = _resolve_marker(inserted=1, sample_ids=[sid], resolve_id='same-resolve')
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[
            _insert_event(sample_id=sid, symbol='ONCE', dedupe_key=key),
            marker,
            dict(marker),
        ],
    )
    if truth['eligible_learning_samples_added_today'] != 1:
        return _fail(f'duplicate markers must not inflate, got {truth}')
    return 0


def test_stable_legacy_modern_dedupe() -> int:
    from backend.trading.daily_learning_truth import (
        is_eligible_historical_learning_sample,
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    legacy = {
        'symbol': 'abc',
        'session_date': '2099-07-01',
        'outcome': 'win',
        'aggregate_key': 'abc|cat|ok|GREEN|breakout',
        'stage_version': '52O',
    }
    modern = {
        'symbol': 'ABC',
        'session_date': '2099-07-01',
        'outcome': 'WIN',
        'aggregate_key': 'abc|cat|ok|GREEN|breakout',
        'stage': 'opening_0920',
        'score': 70,
        'state': 'TRADECARD_CANDIDATE',
    }
    if learning_record_dedupe_key(legacy) != learning_record_dedupe_key(modern):
        return _fail('legacy/modern equivalent records must share dedupe identity')
    ok_l, _ = is_eligible_historical_learning_sample(legacy)
    ok_m, _ = is_eligible_historical_learning_sample(modern)
    if not ok_l or not ok_m:
        return _fail('both legacy and modern forms must be eligible')
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[legacy, modern],
        mutations=[_resolve_marker(inserted=0)],
    )
    if truth['eligible_learning_samples_total'] != 1:
        return _fail(f'legacy+modern must dedupe to 1, got {truth["eligible_learning_samples_total"]}')
    bare = {'symbol': 'ABC', 'outcome': 'WIN'}
    ok_b, _ = is_eligible_historical_learning_sample(bare)
    if ok_b:
        return _fail('bare symbol+WIN must be excluded')
    missing_day = {'symbol': 'ABC', 'outcome': 'WIN', 'aggregate_key': 'x'}
    ok_d, _ = is_eligible_historical_learning_sample(missing_day)
    if ok_d:
        return _fail('missing session date must be excluded')
    missing_id = {'symbol': 'ABC', 'outcome': 'WIN', 'session_date': DAY}
    ok_i, _ = is_eligible_historical_learning_sample(missing_id)
    if ok_i:
        return _fail('missing snapshot_id and aggregate_key must be excluded')
    return 0


def test_historical_total_12_with_proven_zero_today() -> int:
    from backend.trading.daily_learning_truth import (
        format_learning_sample_count_lines,
        reconcile_daily_learning_truth,
    )

    learning = [
        _learning_row(symbol=f'S{i}', session_date='2099-07-01', outcome='WIN')
        for i in range(12)
    ]
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=learning,
        mutations=[_resolve_marker(inserted=0)],
    )
    if truth['eligible_learning_samples_added_today'] != 0:
        return _fail('proven zero today required')
    if truth['eligible_learning_samples_total'] != 12:
        return _fail(f'expected total 12, got {truth["eligible_learning_samples_total"]}')
    lines = '\n'.join(format_learning_sample_count_lines(truth))
    if 'Actual learning sample updated: 12' in lines:
        return _fail('must not reuse cumulative as Actual learning sample updated')
    if 'Eligible learning samples added today: 0' not in lines:
        return _fail(lines)
    if 'Total eligible historical samples: 12' not in lines:
        return _fail(lines)
    return 0


def test_historical_total_12_without_provenance_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        format_learning_sample_count_lines,
        reconcile_daily_learning_truth,
    )

    learning = [
        _learning_row(symbol=f'H{i}', session_date='2099-06-01', outcome='LOSS')
        for i in range(12)
    ]
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=learning,
        mutations=[],
    )
    if truth['daily_added_provenance_available']:
        return _fail('provenance must be unavailable')
    if truth['eligible_learning_samples_added_today'] is not None:
        return _fail('daily added must be null without provenance')
    if truth['eligible_learning_samples_total'] != 12:
        return _fail('total must remain 12')
    lines = '\n'.join(format_learning_sample_count_lines(truth))
    if 'Eligible learning samples added today: unavailable' not in lines:
        return _fail(lines)
    return 0


def test_session_mismatch_yesterday_not_today() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    yday = '2099-07-27'
    row = _learning_row(symbol='OLDCO', session_date=yday)
    key = learning_record_dedupe_key(row)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[
            {
                'event': 'learning_sample_mutation',
                'action': 'inserted',
                'sample_id': row['sample_id'],
                'symbol': 'OLDCO',
                'session_date': yday,
                'dedupe_key': key,
            },
            _resolve_marker(inserted=0),
        ],
    )
    if truth['eligible_learning_samples_added_today'] != 0:
        return _fail('yesterday insertion must not count as added today')
    return 0


def test_malformed_numeric_payloads_safe() -> int:
    from backend.trading.daily_learning_truth import (
        format_learning_sample_count_lines,
        is_canonical_winner_reason_eligible,
        reconcile_daily_learning_truth,
    )

    snap = _quality_snap(score='bad', volume_participation='bad')
    outcome = _win_outcome(score='bad')
    ok, code = is_canonical_winner_reason_eligible(outcome, snapshot=snap, session_date=DAY)
    if ok:
        return _fail('bad score must not create winner eligibility')
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[snap, {'symbol': 'X', 'score': 'bad', 'session_date': DAY}],
        outcomes=[outcome],
        learning_records=[_learning_row(symbol='BAD', session_date=DAY, score='bad')],
        mutations=[_resolve_marker(inserted='bad')],
    )
    lines = '\n'.join(format_learning_sample_count_lines(truth))
    if 'Eligible learning samples added today:' not in lines:
        return _fail('malformed numerics must still render')
    injected = {
        'daily_added_provenance_available': True,
        'eligible_learning_samples_added_today': 'bad',
        'historical_total_available': True,
        'eligible_learning_samples_total': {'n': 1},
        'qualification_reasons': [],
        'winner_reasons': [],
        'reconciliation_ok': True,
    }
    lines2 = '\n'.join(format_learning_sample_count_lines(injected))
    if 'unavailable' not in lines2:
        return _fail(f'malformed injected counts must render unavailable: {lines2}')
    return 0


def test_historical_report_uses_own_session_date() -> int:
    from backend.orchestration.alert_quality_engine import format_daily_review_quality_lines
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    snap_a = _quality_snap(symbol='DAYA', snapshot_id='snap-a', session_date=DAY)
    snap_b = _quality_snap(symbol='DAYB', snapshot_id='snap-b', session_date=DAY_B)
    outcome_a = _win_outcome(symbol='DAYA', snapshot_id='snap-a', session_date=DAY)
    outcome_b = _win_outcome(symbol='DAYB', snapshot_id='snap-b', session_date=DAY_B)
    with patch(
        'backend.trading.daily_learning_truth.reconcile_daily_learning_truth',
        side_effect=lambda session_date=None, **kwargs: reconcile_daily_learning_truth(
            session_date=session_date,
            snapshots=[snap_a, snap_b],
            outcomes=[outcome_a, outcome_b],
            learning_records=[],
            mutations=[_resolve_marker(inserted=0, session_date=session_date or DAY)],
        ),
    ), patch(
        'backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots',
        return_value=False,
    ), patch(
        'backend.trading.candidate_outcome_learning.eligible_learning_symbols',
        return_value=[],
    ), patch(
        'backend.trading.candidate_outcome_learning.format_daily_review_tradecard_outcome_section',
        return_value=[],
    ), patch(
        'backend.trading.candidate_outcome_learning.format_legacy_tradecard_journal_lines',
        return_value=[],
    ):
        lines = format_daily_review_quality_lines(
            tradecard_counts={'generated': 0, 'filled': 0, 'no_fill': 0, 'pending': 0},
            actual_learning_summary={'session_date': DAY, 'sample_updated': 0, 'pending_data': 0, 'pending_reasons': {}},
        )
    text = '\n'.join(lines)
    if 'DAYB' in text:
        return _fail('Day A report must not include Day B winners/candidates')
    if 'DAYA' not in text:
        return _fail('Day A report must include Day A qualification/winner truth')
    return 0


def test_unreadable_learning_file_total_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        format_learning_sample_count_lines,
        reconcile_daily_learning_truth,
    )

    class _BoomPath:
        def is_file(self):
            return True

        def read_text(self, *a, **k):
            raise OSError('permission denied')

    with patch('backend.trading.daily_learning_truth._learning_path', return_value=_BoomPath()):
        truth = reconcile_daily_learning_truth(
            session_date=DAY,
            snapshots=[],
            outcomes=[],
            learning_records=None,
            mutations=[_resolve_marker(inserted=0)],
        )
    if truth.get('historical_total_available') is not False:
        return _fail('unreadable learning store must mark historical total unavailable')
    lines = '\n'.join(format_learning_sample_count_lines(truth))
    if 'Total eligible historical samples: unavailable' not in lines:
        return _fail(lines)
    return 0


def test_formatter_exception_renders_unavailable_not_zero() -> int:
    from backend.orchestration.alert_quality_engine import format_daily_review_quality_lines

    with patch(
        'backend.trading.daily_learning_truth.reconcile_daily_learning_truth',
        side_effect=RuntimeError('boom'),
    ), patch(
        'backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots',
        return_value=False,
    ), patch(
        'backend.trading.candidate_outcome_learning.eligible_learning_symbols',
        return_value=[],
    ), patch(
        'backend.trading.candidate_outcome_learning.format_daily_review_tradecard_outcome_section',
        return_value=[],
    ), patch(
        'backend.trading.candidate_outcome_learning.format_legacy_tradecard_journal_lines',
        return_value=[],
    ):
        lines = format_daily_review_quality_lines(
            tradecard_counts={'generated': 0, 'filled': 0, 'no_fill': 0, 'pending': 0},
            actual_learning_summary={'session_date': DAY, 'pending_data': 0, 'pending_reasons': {}},
        )
    text = '\n'.join(lines)
    if 'Total eligible historical samples: 0' in text:
        return _fail('failure must not invent historical total zero')
    if 'Total eligible historical samples: unavailable' not in text:
        return _fail(text)
    if 'Winner reasons:' in text and '• None recorded today' in text.split('Winner reasons:')[-1]:
        return _fail('failure must not claim Winner reasons none')
    if '• unavailable' not in text:
        return _fail('failure must render unavailable reason sections')
    return 0


def test_valid_empty_and_injected_zero() -> int:
    from backend.trading.daily_learning_truth import format_learning_sample_count_lines, reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
    )
    if truth['eligible_learning_samples_total'] != 0:
        return _fail('valid empty store may report zero')
    lines = '\n'.join(format_learning_sample_count_lines(truth))
    if 'Total eligible historical samples: 0' not in lines:
        return _fail(lines)
    injected = {
        'daily_added_provenance_available': True,
        'eligible_learning_samples_added_today': 0,
        'historical_total_available': True,
        'eligible_learning_samples_total': 0,
        'reconciliation_ok': True,
    }
    lines2 = '\n'.join(format_learning_sample_count_lines(injected))
    if 'Total eligible historical samples: 0' not in lines2:
        return _fail(lines2)
    return 0


def test_duplicate_snapshots_outcomes_do_not_inflate() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    snap = _quality_snap()
    outcome = _win_outcome()
    other = _quality_snap(symbol='WINCO', snapshot_id='snap-other', score=70)
    pending = {**other, 'outcome': 'PENDING_DATA'}
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[snap, dict(snap), other],
        outcomes=[outcome, dict(outcome), pending],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
    )
    if truth['quality_tradecards_tracked_count'] != 2:
        return _fail(f'duplicate snaps must count unique ids, got {truth["quality_tradecards_tracked_count"]}')
    if truth['canonical_outcomes_recorded_count'] != 1:
        return _fail(f'duplicate outcomes must count once, got {truth["canonical_outcomes_recorded_count"]}')
    if len(truth['winner_reasons']) != 1:
        return _fail(f'duplicate winners must produce one reason, got {truth["winner_reasons"]}')
    # unresolved other snapshot must remain visible
    if not any(q.get('snapshot_id') == 'snap-other' for q in truth['qualification_reasons']):
        return _fail('unresolved distinct snapshot must not be hidden by same-symbol winner')
    return 0


def test_decision_trace_cannot_create_winner() -> int:
    from backend.trading.daily_learning_truth import is_canonical_winner_reason_eligible

    outcome = {
        'symbol': 'TRACECO',
        'outcome': 'WIN',
        'score': 90,
        'stage': 'opening_0920',
        'state': 'TRADECARD_CANDIDATE',
        'snapshot_id': 'snap-fake',
        'session_date': DAY,
        'decision_trace': {'outcome_learning_eligible': True},
    }
    ok, code = is_canonical_winner_reason_eligible(outcome, snapshot=None, session_date=DAY)
    if ok or code != 'no_quality_tradecard':
        return _fail(f'trace cannot create winner without persisted snapshot, got {ok}/{code}')
    return 0


def test_read_only_rendering_guards() -> int:
    import subprocess
    import sys
    import types
    from contextlib import ExitStack

    # Pre-import modules later tests need so patch teardown cannot poison first import.
    import backend.analytics.actual_learning_resolver  # noqa: F401
    import backend.orchestration.alert_quality_engine  # noqa: F401

    from backend.trading.daily_learning_truth import (
        format_daily_learning_truth_lines,
        reconcile_daily_learning_truth,
    )

    before = subprocess.check_output(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    boom = AssertionError('prohibited_mutation')
    snap = _quality_snap()
    outcome = _win_outcome()
    truth_input = dict(
        session_date=DAY,
        snapshots=[snap],
        outcomes=[outcome],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
    )
    stub = types.ModuleType('backend.ai.ai_router')
    stub.ask_ai = lambda *a, **k: (_ for _ in ()).throw(boom)  # type: ignore[attr-defined]
    patches = [
        patch('backend.telegram.ai_usage_guard.guarded_ask_ai', side_effect=boom),
        patch('backend.analytics.broker_intelligence.refresh_broker_intelligence', side_effect=boom),
        patch('backend.trading.tradecard_refresh._run_lightweight_refresh', side_effect=boom),
        patch('backend.storage.outcome_resolver.run_outcome_resolver_once', side_effect=boom),
        patch('backend.trading.tradecard_journal.persist_tradecard_generation', side_effect=boom),
        patch('backend.trading.candidate_outcome_learning._append_jsonl', side_effect=boom),
        patch('backend.trading.candidate_outcome_learning._update_learning_aggregate', side_effect=boom),
        patch('backend.trading.candidate_outcome_learning.resolve_candidate_outcomes', side_effect=boom),
        patch('backend.trading.daily_learning_truth.record_learning_sample_mutation', side_effect=boom),
        patch('backend.trading.daily_learning_truth.record_learning_resolve_provenance', side_effect=boom),
    ]
    with ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, {'backend.ai.ai_router': stub}))
        for p in patches:
            stack.enter_context(p)
        a = reconcile_daily_learning_truth(**truth_input)
        b = reconcile_daily_learning_truth(**truth_input)
        text_a = '\n'.join(format_daily_learning_truth_lines(a))
        text_b = '\n'.join(format_daily_learning_truth_lines(b))
    if a != b or text_a != text_b:
        return _fail('identical inputs must produce identical truth and text')
    after = subprocess.check_output(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    if before != after:
        return _fail('focused rendering must not change repository data/ status')
    return 0


def test_old_daily_review_render_compatible() -> int:
    from backend.orchestration.alert_quality_engine import format_daily_review_quality_lines

    with patch(
        'backend.trading.daily_learning_truth.reconcile_daily_learning_truth',
        return_value={
            'session_date': DAY,
            'candidate_observed_count': 0,
            'candidate_qualifying_count': 0,
            'quality_tradecards_tracked_count': 0,
            'canonical_outcomes_recorded_count': 0,
            'eligible_learning_samples_added_today': None,
            'eligible_learning_samples_total': 0,
            'daily_added_provenance_available': False,
            'historical_total_available': True,
            'learning_store_status': 'ok',
            'reason_sections_available': True,
            'source_errors': [],
            'qualification_reasons': [],
            'winner_reasons': [],
            'unresolved_candidates': [],
            'reference_only_candidates': [],
            'deduped_sample_ids': [],
            'source_files': [],
            'reason_codes': [],
            'reconciliation_ok': True,
        },
    ), patch(
        'backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots',
        return_value=False,
    ), patch(
        'backend.trading.candidate_outcome_learning.eligible_learning_symbols',
        return_value=[],
    ), patch(
        'backend.trading.candidate_outcome_learning.format_daily_review_tradecard_outcome_section',
        return_value=['No quality tradecard snapshots today.'],
    ), patch(
        'backend.trading.candidate_outcome_learning.format_legacy_tradecard_journal_lines',
        return_value=[],
    ):
        lines = format_daily_review_quality_lines(
            tradecard_counts={'generated': 0, 'filled': 0, 'no_fill': 0, 'pending': 0},
            actual_learning_summary={
                'session_date': DAY,
                'sample_updated': 12,
                'pending_data': 0,
                'pending_reasons': {},
            },
        )
    text = '\n'.join(lines)
    if 'Actual learning sample updated: 12' in text:
        return _fail('must not show cumulative 12 as Actual learning sample updated')
    if 'Eligible learning samples added today: unavailable' not in text:
        return _fail(text)
    return 0


def test_validator_is_read_only() -> int:
    import subprocess

    watched = [
        PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
        PROJECT_ROOT / 'backend' / 'trading' / 'daily_learning_truth.py',
        PROJECT_ROOT / 'scripts' / 'validate_daily_review_learning_truth_52q.py',
    ]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in watched if p.is_file()}
    src = (PROJECT_ROOT / 'scripts' / 'validate_daily_review_learning_truth_52q.py').read_text(encoding='utf-8')
    promote_needle = 'def ' + '_promote_build'
    write_needle = '.' + 'write_text('
    if promote_needle in src or write_needle in src:
        return _fail('validator source must not contain write/promote helpers')
    # Structural check only here; full validator run is separate.
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in watched if p.is_file()}
    if before != after:
        return _fail('validator source inspection mutated files')
    return 0



def test_two_legitimate_resolve_passes_total_two() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    a = _learning_row(symbol='PASS_A', session_date=DAY)
    b = _learning_row(symbol='PASS_B', session_date=DAY)
    ka, kb = learning_record_dedupe_key(a), learning_record_dedupe_key(b)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[a, b],
        mutations=[
            _insert_event(sample_id=a['sample_id'], symbol='PASS_A', dedupe_key=ka),
            _resolve_marker(inserted=1, sample_ids=[a['sample_id']], resolve_id='resolve-pass-a'),
            _insert_event(sample_id=b['sample_id'], symbol='PASS_B', dedupe_key=kb),
            _resolve_marker(inserted=1, sample_ids=[b['sample_id']], resolve_id='resolve-pass-b'),
        ],
    )
    if truth['eligible_learning_samples_added_today'] != 2:
        return _fail(f'two passes must total 2, got {truth}')
    return 0


def test_idempotent_second_pass_does_not_inflate() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    row = _learning_row(symbol='IDEMP', session_date=DAY)
    key = learning_record_dedupe_key(row)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[
            _insert_event(sample_id=row['sample_id'], symbol='IDEMP', dedupe_key=key),
            _resolve_marker(inserted=1, sample_ids=[row['sample_id']], resolve_id='resolve-1'),
            _resolve_marker(inserted=0, deduplicated=1, sample_ids=[], resolve_id='resolve-2'),
        ],
    )
    if truth['eligible_learning_samples_added_today'] != 1:
        return _fail(f'idempotent second pass must keep 1, got {truth}')
    return 0


def test_duplicate_same_resolve_id_does_not_inflate() -> int:
    return test_duplicate_resolve_markers_do_not_inflate()


def test_conflicting_same_resolve_id_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    row = _learning_row(symbol='CONF', session_date=DAY)
    key = learning_record_dedupe_key(row)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[
            _insert_event(sample_id=row['sample_id'], symbol='CONF', dedupe_key=key),
            _resolve_marker(inserted=1, sample_ids=[row['sample_id']], resolve_id='conflict-id'),
            _resolve_marker(inserted=0, sample_ids=[], resolve_id='conflict-id'),
        ],
    )
    if truth['daily_added_provenance_available'] or truth['eligible_learning_samples_added_today'] is not None:
        return _fail('conflicting same resolve_id must be unavailable')
    return 0


def test_marker_inserted_must_equal_unique_sample_ids() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    row = _learning_row(symbol='MISMATCH', session_date=DAY)
    key = learning_record_dedupe_key(row)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[
            _insert_event(sample_id=row['sample_id'], symbol='MISMATCH', dedupe_key=key),
            _resolve_marker(inserted=2, sample_ids=[row['sample_id']], resolve_id='bad-count'),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('marker inserted must equal unique sample_ids')
    return 0


def test_ambiguous_multiple_legacy_markers_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            _resolve_marker(inserted=0, legacy=True),
            _resolve_marker(inserted=1, sample_ids=['x'], legacy=True),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('ambiguous legacy markers must be unavailable')
    return 0


def test_event_key_and_sample_id_must_match_same_record() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    a = _learning_row(symbol='KEYA', session_date=DAY)
    b = _learning_row(symbol='KEYB', session_date=DAY)
    ka = learning_record_dedupe_key(a)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[a, b],
        mutations=[
            _insert_event(sample_id=b['sample_id'], symbol='KEYA', dedupe_key=ka),
            _resolve_marker(inserted=1, sample_ids=[b['sample_id']], resolve_id='cross'),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('conflicting key/sample_id must make provenance unavailable')
    return 0


def test_event_symbol_mismatch_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    row = _learning_row(symbol='SYMCO', session_date=DAY)
    key = learning_record_dedupe_key(row)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[
            _insert_event(sample_id=row['sample_id'], symbol='OTHER', dedupe_key=key),
            _resolve_marker(inserted=1, sample_ids=[row['sample_id']], resolve_id='sym-mismatch'),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('event symbol mismatch must be unavailable')
    return 0


def test_unknown_supplied_sample_id_not_ignored() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    row = _learning_row(symbol='UNKSID', session_date=DAY)
    key = learning_record_dedupe_key(row)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[
            {
                'event': 'learning_sample_mutation',
                'action': 'inserted',
                'sample_id': 'unknown-sample',
                'symbol': 'UNKSID',
                'session_date': DAY,
                'dedupe_key': key,
            },
            _resolve_marker(inserted=1, sample_ids=[row['sample_id']], resolve_id='unk-sid'),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('unknown sample_id with matching key must not be ignored')
    return 0


def test_unknown_supplied_dedupe_key_not_ignored() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    row = _learning_row(symbol='UNKKEY', session_date=DAY)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[
            {
                'event': 'learning_sample_mutation',
                'action': 'inserted',
                'sample_id': row['sample_id'],
                'symbol': 'UNKKEY',
                'session_date': DAY,
                'dedupe_key': 'unknown-key',
            },
            _resolve_marker(inserted=1, sample_ids=[row['sample_id']], resolve_id='unk-key'),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('unknown dedupe_key with matching sample_id must not be ignored')
    return 0


def test_same_day_orphan_store_zero_marker_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    row = _learning_row(symbol='ORPHSTORE', session_date=DAY)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[_resolve_marker(inserted=0, resolve_id='zero-pass')],
    )
    if truth['daily_added_provenance_available'] or truth['eligible_learning_samples_added_today'] is not None:
        return _fail('same-day recorded sample without event must be unavailable')
    return 0


def test_historical_same_session_other_recorded_at_not_today() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    row = _learning_row(
        symbol='HISTSESS',
        session_date=DAY,
        recorded_at='2099-06-01T16:00:00+05:30',
    )
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[_resolve_marker(inserted=0, resolve_id='hist-zero')],
    )
    if truth['eligible_learning_samples_added_today'] != 0:
        return _fail('historical recorded_at must not inflate today')
    return 0


def test_malformed_learning_jsonl_historical_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        format_learning_sample_count_lines,
        reconcile_daily_learning_truth,
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'candidate_learning_records.jsonl'
        path.write_text(
            '{"symbol":"OK","outcome":"WIN","session_date":"2099-07-01","aggregate_key":"k","stage_version":"52O"}\nNOT_JSON\n',
            encoding='utf-8',
        )
        with patch('backend.trading.daily_learning_truth._learning_path', return_value=path):
            truth = reconcile_daily_learning_truth(
                session_date=DAY,
                snapshots=[],
                outcomes=[],
                learning_records=None,
                mutations=[_resolve_marker(inserted=0)],
            )
    if truth.get('historical_total_available') is not False:
        return _fail('malformed learning JSONL must make historical total unavailable')
    if 'Total eligible historical samples: unavailable' not in '\n'.join(format_learning_sample_count_lines(truth)):
        return _fail('malformed learning must render unavailable')
    return 0


def test_malformed_snapshot_outcome_reason_sections_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        format_daily_learning_truth_lines,
        reconcile_daily_learning_truth,
    )

    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / 'candidate_snapshots.jsonl'
        out = Path(tmp) / 'candidate_outcomes.jsonl'
        snap.write_text('{bad json\n', encoding='utf-8')
        out.write_text('{also bad\n', encoding='utf-8')
        with patch('backend.trading.daily_learning_truth._snapshots_path', return_value=snap), patch(
            'backend.trading.daily_learning_truth._outcomes_path', return_value=out
        ):
            truth = reconcile_daily_learning_truth(
                session_date=DAY,
                snapshots=None,
                outcomes=None,
                learning_records=[],
                mutations=[_resolve_marker(inserted=0)],
            )
    if truth.get('reason_sections_available') is not False:
        return _fail('malformed snapshot/outcome must disable reason sections')
    text = '\n'.join(format_daily_learning_truth_lines(truth))
    if '• None recorded today' in text:
        return _fail('malformed stores must not render none recorded')
    if '• unavailable' not in text:
        return _fail(text)
    return 0


def test_malformed_mutation_jsonl_daily_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'candidate_learning_mutations.jsonl'
        path.write_text('NOT_JSON\n', encoding='utf-8')
        with patch('backend.trading.daily_learning_truth._mutations_path', return_value=path):
            truth = reconcile_daily_learning_truth(
                session_date=DAY,
                snapshots=[],
                outcomes=[],
                learning_records=[],
                mutations=None,
            )
    if truth.get('daily_added_provenance_available'):
        return _fail('malformed mutations must make daily-added unavailable')
    return 0


def test_missing_first_run_learning_file_total_zero() -> int:
    from backend.trading.daily_learning_truth import (
        format_learning_sample_count_lines,
        reconcile_daily_learning_truth,
    )

    missing = Path('definitely-missing-learning-52q.jsonl')
    with patch('backend.trading.daily_learning_truth._learning_path', return_value=missing):
        truth = reconcile_daily_learning_truth(
            session_date=DAY,
            snapshots=[],
            outcomes=[],
            learning_records=None,
            mutations=[_resolve_marker(inserted=0)],
        )
    if truth.get('learning_store_status') != 'missing':
        return _fail(f'expected missing status, got {truth.get("learning_store_status")}')
    if truth.get('eligible_learning_samples_total') != 0:
        return _fail('missing first-run store may report zero')
    if 'Total eligible historical samples: 0' not in '\n'.join(format_learning_sample_count_lines(truth)):
        return _fail('missing store must render zero')
    return 0


def test_snapshot_store_failure_reason_sections_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        format_daily_learning_truth_lines,
        reconcile_daily_learning_truth,
    )

    class _Boom:
        def is_file(self):
            return True

        def read_text(self, *a, **k):
            raise OSError('denied')

    with patch('backend.trading.daily_learning_truth._snapshots_path', return_value=_Boom()):
        truth = reconcile_daily_learning_truth(
            session_date=DAY,
            snapshots=None,
            outcomes=[],
            learning_records=[],
            mutations=[_resolve_marker(inserted=0)],
        )
    if truth.get('reason_sections_available') is not False:
        return _fail('snapshot store failure must disable reason sections')
    text = '\n'.join(format_daily_learning_truth_lines(truth))
    if 'None recorded today' in text:
        return _fail(text)
    return 0


def test_outcome_store_failure_reason_sections_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        format_daily_learning_truth_lines,
        reconcile_daily_learning_truth,
    )

    class _Boom:
        def is_file(self):
            return True

        def read_text(self, *a, **k):
            raise OSError('denied')

    with patch('backend.trading.daily_learning_truth._outcomes_path', return_value=_Boom()):
        truth = reconcile_daily_learning_truth(
            session_date=DAY,
            snapshots=[],
            outcomes=None,
            learning_records=[],
            mutations=[_resolve_marker(inserted=0)],
        )
    if truth.get('reason_sections_available') is not False:
        return _fail('outcome store failure must disable reason sections')
    text = '\n'.join(format_daily_learning_truth_lines(truth))
    if 'None recorded today' in text:
        return _fail(text)
    return 0


def test_source_failure_never_renders_none_recorded_today() -> int:
    return test_snapshot_store_failure_reason_sections_unavailable()


def test_failed_injected_truth_hides_stale_numbers() -> int:
    from backend.trading.daily_learning_truth import (
        format_daily_learning_truth_lines,
        format_learning_sample_count_lines,
    )

    truth = {
        'reconciliation_ok': False,
        'daily_added_provenance_available': True,
        'historical_total_available': True,
        'eligible_learning_samples_added_today': 9,
        'eligible_learning_samples_total': 99,
        'reason_sections_available': True,
        'qualification_reasons': [],
        'winner_reasons': [],
    }
    counts = '\n'.join(format_learning_sample_count_lines(truth))
    full = '\n'.join(format_daily_learning_truth_lines(truth))
    if '9' in counts or '99' in counts:
        return _fail(f'failed injected truth must hide stale counts: {counts}')
    if 'unavailable' not in counts or 'unavailable' not in full:
        return _fail(counts + '\n' + full)
    if 'None recorded today' in full:
        return _fail('failed injected truth must not claim none recorded')
    return 0


def test_legacy_requires_stage_version() -> int:
    from backend.trading.daily_learning_truth import (
        is_eligible_historical_learning_sample,
        reconcile_daily_learning_truth,
    )

    ok_legacy, _ = is_eligible_historical_learning_sample({
        'symbol': 'LEG',
        'session_date': '2099-07-01',
        'outcome': 'WIN',
        'aggregate_key': 'leg|cat|ok|GREEN|breakout',
        'stage_version': '52O',
    })
    if not ok_legacy:
        return _fail('legacy with stage_version must remain eligible')
    bad, _ = is_eligible_historical_learning_sample({
        'symbol': 'LEG',
        'session_date': '2099-07-01',
        'outcome': 'WIN',
        'aggregate_key': 'leg|cat|ok|GREEN|breakout',
    })
    if bad:
        return _fail('legacy without stage_version must be excluded')
    fake, _ = is_eligible_historical_learning_sample({
        'symbol': 'FAKE',
        'session_date': '2099-07-01',
        'outcome': 'WIN',
        'aggregate_key': 'arbitrary-fake-key',
        'fake': True,
        'stage_version': '52O',
    })
    if fake:
        return _fail('fake aggregate key must not create eligibility')
    learning = [
        _learning_row(symbol=f'S{i}', session_date='2099-07-01', outcome='WIN')
        for i in range(12)
    ]
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=learning,
        mutations=[_resolve_marker(inserted=0)],
    )
    if truth['eligible_learning_samples_total'] != 12:
        return _fail(f'historical-total-12 fixture must remain 12, got {truth}')
    return 0


def test_quality_tracked_requires_snapshot_id() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    valid = _quality_snap()
    no_id = _quality_snap(snapshot_id='')
    captured = _quality_snap(snapshot_id='snap-cap', captured_only=True)
    candidate = _quality_snap(snapshot_id='snap-cand', candidate_only='true')
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[valid, dict(valid), no_id, captured, candidate],
        outcomes=[],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
    )
    if truth['quality_tradecards_tracked_count'] != 1:
        return _fail(f'expected quality tracked 1, got {truth["quality_tradecards_tracked_count"]}')
    return 0


def test_malformed_summary_fields_safe() -> int:
    from backend.analytics.actual_learning_resolver import format_actual_learning_close_lines
    from backend.orchestration.alert_quality_engine import format_daily_review_quality_lines

    summary = {
        'session_date': DAY,
        'watchlist': {'win': 'bad', 'loss': [], 'neutral': {'x': 1}},
        'avoid': {'success': 'NaN', 'fail': 'Infinity'},
        'pending_data': 'bad',
        'pending_reasons': {},
        'tradecard': {'resolved': None, 'no_fill': 'x'},
        'daily_learning_truth': {
            'reconciliation_ok': True,
            'daily_added_provenance_available': True,
            'historical_total_available': True,
            'eligible_learning_samples_added_today': 0,
            'eligible_learning_samples_total': 0,
            'reason_sections_available': True,
            'qualification_reasons': [],
            'winner_reasons': [],
        },
        'explanation': {},
    }
    try:
        close = format_actual_learning_close_lines(summary)
        review = format_daily_review_quality_lines(
            tradecard_counts={'generated': 'bad', 'filled': [], 'pending': {}},
            actual_learning_summary=summary,
        )
    except Exception as exc:
        return _fail(f'malformed summary must not crash: {exc}')
    text = '\n'.join(close + review)
    if 'Eligible learning samples added today: 0' not in text:
        return _fail(text)
    return 0


def test_import_failure_fallback_no_unbound() -> int:
    import sys
    from backend.orchestration.alert_quality_engine import format_daily_review_quality_lines

    # Force the local import inside the formatter try-block to fail without
    # patching builtins.__import__ (which destabilizes the interpreter).
    with patch.dict(sys.modules, {'backend.trading.daily_learning_truth': None}), patch(
        'backend.trading.candidate_outcome_learning.has_eligible_quality_snapshots',
        return_value=False,
    ), patch(
        'backend.trading.candidate_outcome_learning.eligible_learning_symbols',
        return_value=[],
    ), patch(
        'backend.trading.candidate_outcome_learning.format_daily_review_tradecard_outcome_section',
        return_value=[],
    ), patch(
        'backend.trading.candidate_outcome_learning.format_legacy_tradecard_journal_lines',
        return_value=[],
    ):
        try:
            lines = format_daily_review_quality_lines(
                tradecard_counts={'generated': 0, 'filled': 0, 'no_fill': 0, 'pending': 0},
                actual_learning_summary={'session_date': DAY},
            )
        except UnboundLocalError as exc:
            return _fail(f'import failure must not raise UnboundLocalError: {exc}')
        except Exception as exc:
            return _fail(f'unexpected crash: {exc}')
    text = '\n'.join(lines)
    if 'Total eligible historical samples: unavailable' not in text:
        return _fail(text)
    if 'Winner reasons:' in text and '• unavailable' not in text:
        return _fail(text)
    return 0



def test_orphan_both_unknown_with_zero_marker_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            {
                'event': 'learning_sample_mutation',
                'action': 'inserted',
                'sample_id': 'unknown-sid',
                'symbol': 'ORPH',
                'session_date': DAY,
                'dedupe_key': 'unknown-key',
            },
            _resolve_marker(inserted=0, resolve_id='zero-orphan'),
        ],
    )
    if truth['daily_added_provenance_available'] or truth['eligible_learning_samples_added_today'] is not None:
        return _fail('orphan unknown identities must not allow proven zero')
    if 'daily_provenance_inconsistent' not in truth['reason_codes']:
        return _fail('expected daily_provenance_inconsistent')
    return 0


def test_missing_event_identities_with_zero_marker_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            {
                'event': 'learning_sample_mutation',
                'action': 'inserted',
                'sample_id': '',
                'symbol': 'MISS',
                'session_date': DAY,
                'dedupe_key': '',
            },
            _resolve_marker(inserted=0, resolve_id='zero-missing-ids'),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('missing event identities must make provenance unavailable')
    return 0


def test_only_unknown_key_with_zero_marker_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            {
                'event': 'learning_sample_mutation',
                'action': 'inserted',
                'sample_id': '',
                'symbol': 'ONLYKEY',
                'session_date': DAY,
                'dedupe_key': 'only-unknown-key',
            },
            _resolve_marker(inserted=0, resolve_id='zero-only-key'),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('only unknown key must make provenance unavailable')
    return 0


def test_only_unknown_sample_id_with_zero_marker_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            {
                'event': 'learning_sample_mutation',
                'action': 'inserted',
                'sample_id': 'only-unknown-sid',
                'symbol': 'ONLYSID',
                'session_date': DAY,
                'dedupe_key': '',
            },
            _resolve_marker(inserted=0, resolve_id='zero-only-sid'),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('only unknown sample_id must make provenance unavailable')
    return 0


def test_ineligible_persisted_record_event_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    row = _learning_row(symbol='BADREC', session_date=DAY, score=10)
    # Force ineligible modern score while keeping identities for the event.
    key = learning_record_dedupe_key(row)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[
            _insert_event(sample_id=row['sample_id'], symbol='BADREC', dedupe_key=key),
            _resolve_marker(inserted=1, sample_ids=[row['sample_id']], resolve_id='inel-rec'),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('ineligible persisted record must make event provenance unavailable')
    return 0


def test_historical_candidate_only_excluded() -> int:
    from backend.trading.daily_learning_truth import is_eligible_historical_learning_sample

    ok, code = is_eligible_historical_learning_sample(
        _learning_row(symbol='CAND', session_date='2099-07-01', candidate_only=True)
    )
    if ok or code != 'candidate_only':
        return _fail(f'candidate_only=True must be excluded, got {ok}/{code}')
    return 0


def test_historical_captured_only_excluded() -> int:
    from backend.trading.daily_learning_truth import is_eligible_historical_learning_sample

    ok, code = is_eligible_historical_learning_sample(
        _learning_row(symbol='CAP', session_date='2099-07-01', captured_only=True)
    )
    if ok or code != 'candidate_only':
        return _fail(f'captured_only=True must be excluded, got {ok}/{code}')
    return 0


def test_historical_string_truthy_flags_excluded() -> int:
    from backend.trading.daily_learning_truth import is_eligible_historical_learning_sample

    for flag, value in (
        ('candidate_only', 'true'),
        ('captured_only', 'yes'),
        ('captured_only', 1),
    ):
        row = _learning_row(symbol='FLAG', session_date='2099-07-01', **{flag: value})
        ok, _ = is_eligible_historical_learning_sample(row)
        if ok:
            return _fail(f'{flag}={value!r} must be excluded')
    return 0


def test_historical_false_string_flag_not_truthy() -> int:
    from backend.trading.daily_learning_truth import is_eligible_historical_learning_sample

    ok, _ = is_eligible_historical_learning_sample(
        _learning_row(symbol='OKFLAG', session_date='2099-07-01', candidate_only='false')
    )
    if not ok:
        return _fail('candidate_only="false" must not reject solely by that flag')
    return 0


def test_accepted_legacy_stage_version_remains_eligible() -> int:
    from backend.trading.daily_learning_truth import is_eligible_historical_learning_sample

    for version in ('52O', '52o', '4B.18K-A', ' 4b.18k-a '):
        ok, _ = is_eligible_historical_learning_sample({
            'symbol': 'LEG',
            'session_date': '2099-07-01',
            'outcome': 'WIN',
            'aggregate_key': 'leg|cat|ok|GREEN|breakout',
            'stage_version': version,
        })
        if not ok:
            return _fail(f'accepted legacy stage_version {version!r} must remain eligible')
    return 0


def test_arbitrary_legacy_stage_version_excluded() -> int:
    from backend.trading.daily_learning_truth import is_eligible_historical_learning_sample

    for version in ('garbage', '52R', 'future-only', ''):
        ok, _ = is_eligible_historical_learning_sample({
            'symbol': 'LEG',
            'session_date': '2099-07-01',
            'outcome': 'WIN',
            'aggregate_key': 'leg|cat|ok|GREEN|breakout',
            'stage_version': version,
        })
        if ok:
            return _fail(f'arbitrary stage_version {version!r} must be excluded')
    return 0


def test_legacy_candidate_only_excluded() -> int:
    from backend.trading.daily_learning_truth import is_eligible_historical_learning_sample

    ok, code = is_eligible_historical_learning_sample({
        'symbol': 'LEG',
        'session_date': '2099-07-01',
        'outcome': 'WIN',
        'aggregate_key': 'leg|cat|ok|GREEN|breakout',
        'stage_version': '52O',
        'candidate_only': True,
    })
    if ok or code != 'candidate_only':
        return _fail(f'legacy candidate_only must be excluded, got {ok}/{code}')
    return 0


def test_outcome_without_canonical_id_not_counted() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[{
            'symbol': 'NOID',
            'session_date': DAY,
            'outcome': 'WIN',
            'reason_summary': 'symbol-only win',
        }],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
    )
    if truth['canonical_outcomes_recorded_count'] != 0:
        return _fail('identity-less outcome must not count as canonical')
    if truth['winner_reasons']:
        return _fail('identity-less WIN must not create winner reasons')
    if not any(q.get('reason_code') == 'no_canonical_outcome' for q in truth['qualification_reasons']):
        return _fail('identity-less outcome should appear as no_canonical_outcome')
    return 0


def test_two_symbol_only_outcomes_do_not_collapse() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[
            {'symbol': 'AAA', 'session_date': DAY, 'outcome': 'LOSS', 'reason_summary': 'a'},
            {'symbol': 'BBB', 'session_date': DAY, 'outcome': 'LOSS', 'reason_summary': 'b'},
        ],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
    )
    quals = [q for q in truth['qualification_reasons'] if q.get('reason_code') == 'no_canonical_outcome']
    syms = {q.get('symbol') for q in quals}
    if syms != {'AAA', 'BBB'}:
        return _fail(f'two symbol-only outcomes must not collapse, got {quals}')
    return 0


def test_duplicate_noncanonical_outcomes_dedupe_deterministically() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    row = {'symbol': 'DUPNC', 'session_date': DAY, 'outcome': 'NEUTRAL', 'reason_summary': 'same'}
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[row, dict(row)],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
    )
    quals = [q for q in truth['qualification_reasons'] if q.get('symbol') == 'DUPNC']
    if len(quals) != 1:
        return _fail(f'duplicate noncanonical rows must dedupe once, got {quals}')
    return 0


def test_noncanonical_win_never_creates_winner_reason() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[{
            'symbol': 'FAKEWIN',
            'session_date': DAY,
            'outcome': 'WIN',
            'score': 99,
            'stage': 'opening_0920',
            'state': 'TRADECARD_CANDIDATE',
            'reason_summary': 'copied fields without snapshot_id',
        }],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
    )
    if any(w.get('symbol') == 'FAKEWIN' for w in truth['winner_reasons']):
        return _fail('noncanonical WIN must never create winner reason')
    return 0


def test_repeated_reconciliation_is_byte_deterministic() -> int:
    import json
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    kwargs = dict(
        session_date=DAY,
        snapshots=[_quality_snap(), _quality_snap(snapshot_id='snap-2', symbol='OTHER')],
        outcomes=[
            _win_outcome(),
            {'symbol': 'AAA', 'session_date': DAY, 'outcome': 'LOSS', 'reason_summary': 'a'},
            {'symbol': 'BBB', 'session_date': DAY, 'outcome': 'LOSS', 'reason_summary': 'b'},
        ],
        learning_records=[_learning_row(symbol='H1', session_date='2099-07-01')],
        mutations=[_resolve_marker(inserted=0)],
        observed_candidates=[{'ticker': 'OBS', 'score': 70, 'why': ['x']}],
    )
    a = reconcile_daily_learning_truth(**kwargs)
    b = reconcile_daily_learning_truth(**kwargs)
    ja = json.dumps(a, sort_keys=True, ensure_ascii=False)
    jb = json.dumps(b, sort_keys=True, ensure_ascii=False)
    if ja != jb:
        return _fail('repeated reconciliation must be byte-deterministic')
    return 0


def test_missing_reason_availability_preserves_counts() -> int:
    from backend.trading.daily_learning_truth import (
        format_daily_learning_truth_lines,
        format_learning_sample_count_lines,
    )

    truth = {
        'reconciliation_ok': True,
        'daily_added_provenance_available': True,
        'historical_total_available': True,
        'eligible_learning_samples_added_today': 0,
        'eligible_learning_samples_total': 12,
        # reason_sections_available intentionally missing
        'qualification_reasons': [],
        'winner_reasons': [],
    }
    counts = '\n'.join(format_learning_sample_count_lines(truth))
    full = '\n'.join(format_daily_learning_truth_lines(truth))
    if 'Eligible learning samples added today: 0' not in counts:
        return _fail(counts)
    if 'Total eligible historical samples: 12' not in counts:
        return _fail(counts)
    if 'Eligible learning samples added today: 0' not in full:
        return _fail(full)
    if '• unavailable' not in full:
        return _fail('missing reason availability must render reasons unavailable')
    if 'None recorded today' in full:
        return _fail('missing reason availability must not claim none recorded')
    return 0


def test_malformed_reason_availability_never_none_recorded() -> int:
    from backend.trading.daily_learning_truth import format_daily_learning_truth_lines

    truth = {
        'reconciliation_ok': True,
        'daily_added_provenance_available': True,
        'historical_total_available': True,
        'eligible_learning_samples_added_today': 0,
        'eligible_learning_samples_total': 0,
        'reason_sections_available': 'bad',
        'qualification_reasons': [],
        'winner_reasons': [],
    }
    full = '\n'.join(format_daily_learning_truth_lines(truth))
    if 'None recorded today' in full:
        return _fail(full)
    if '• unavailable' not in full:
        return _fail(full)
    return 0



def test_winner_missing_state_rejected() -> int:
    from backend.trading.daily_learning_truth import is_canonical_winner_reason_eligible

    snap = _quality_snap()
    snap.pop('state', None)
    ok, code = is_canonical_winner_reason_eligible(_win_outcome(), snapshot=snap, session_date=DAY)
    if ok or code != 'no_quality_tradecard':
        return _fail(f'missing state must reject winner, got {ok}/{code}')
    return 0


def test_winner_unknown_state_rejected() -> int:
    from backend.trading.daily_learning_truth import is_canonical_winner_reason_eligible

    snap = _quality_snap(state='ARBITRARY_OK_LOOKING')
    ok, code = is_canonical_winner_reason_eligible(_win_outcome(), snapshot=snap, session_date=DAY)
    if ok or code != 'no_quality_tradecard':
        return _fail(f'unknown state must reject winner, got {ok}/{code}')
    return 0


def test_historical_missing_state_excluded() -> int:
    from backend.trading.daily_learning_truth import is_eligible_historical_learning_sample

    row = _learning_row(symbol='NOST', session_date='2099-07-01')
    row.pop('state', None)
    ok, _ = is_eligible_historical_learning_sample(row)
    if ok:
        return _fail('modern historical row missing state must be excluded')
    return 0


def test_historical_unknown_state_excluded() -> int:
    from backend.trading.daily_learning_truth import is_eligible_historical_learning_sample

    ok, _ = is_eligible_historical_learning_sample(
        _learning_row(symbol='UNKST', session_date='2099-07-01', state='WEIRD_STATE')
    )
    if ok:
        return _fail('unknown historical state must be excluded')
    return 0


def test_quality_tracked_unknown_state_excluded() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[_quality_snap(state='UNKNOWN_STATE')],
        outcomes=[],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
    )
    if truth['quality_tradecards_tracked_count'] != 0:
        return _fail('unknown state must not count as quality tracked')
    return 0


def test_genuine_writer_state_remains_eligible() -> int:
    from backend.trading.daily_learning_truth import (
        is_canonical_winner_reason_eligible,
        is_eligible_historical_learning_sample,
        reconcile_daily_learning_truth,
    )

    snap = _quality_snap(state='TRADECARD_CANDIDATE')
    ok_w, _ = is_canonical_winner_reason_eligible(_win_outcome(), snapshot=snap, session_date=DAY)
    ok_h, _ = is_eligible_historical_learning_sample(
        _learning_row(symbol='GEN', session_date='2099-07-01', state='TRADECARD_CANDIDATE')
    )
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[snap],
        outcomes=[],
        learning_records=[],
        mutations=[_resolve_marker(inserted=0)],
    )
    if not ok_w or not ok_h or truth['quality_tradecards_tracked_count'] != 1:
        return _fail('TRADECARD_CANDIDATE must remain eligible')
    return 0


def test_unreadable_learning_store_daily_and_total_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        format_learning_sample_count_lines,
        reconcile_daily_learning_truth,
    )

    class _Boom:
        def is_file(self):
            return True

        def read_text(self, *a, **k):
            raise OSError('denied')

    with patch('backend.trading.daily_learning_truth._learning_path', return_value=_Boom()):
        truth = reconcile_daily_learning_truth(
            session_date=DAY,
            snapshots=[],
            outcomes=[],
            learning_records=None,
            mutations=[_resolve_marker(inserted=0)],
        )
    if truth.get('daily_added_provenance_available') or truth.get('historical_total_available'):
        return _fail('unreadable learning store must invalidate daily and total')
    if 'learning_store_unavailable' not in truth.get('reason_codes', []):
        return _fail('expected learning_store_unavailable')
    lines = '\n'.join(format_learning_sample_count_lines(truth))
    if 'Eligible learning samples added today: unavailable' not in lines:
        return _fail(lines)
    if 'Total eligible historical samples: unavailable' not in lines:
        return _fail(lines)
    return 0


def test_malformed_learning_store_daily_and_total_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        format_learning_sample_count_lines,
        reconcile_daily_learning_truth,
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'candidate_learning_records.jsonl'
        path.write_text('NOT_JSON\n', encoding='utf-8')
        with patch('backend.trading.daily_learning_truth._learning_path', return_value=path):
            truth = reconcile_daily_learning_truth(
                session_date=DAY,
                snapshots=[],
                outcomes=[],
                learning_records=None,
                mutations=[_resolve_marker(inserted=0)],
            )
    if truth.get('daily_added_provenance_available') or truth.get('historical_total_available'):
        return _fail('malformed learning store must invalidate daily and total')
    lines = '\n'.join(format_learning_sample_count_lines(truth))
    if 'unavailable' not in lines:
        return _fail(lines)
    return 0


def test_zero_marker_cannot_override_unreadable_learning_store() -> int:
    return test_unreadable_learning_store_daily_and_total_unavailable()


def test_missing_first_run_store_still_allows_proven_zero() -> int:
    from backend.trading.daily_learning_truth import (
        format_learning_sample_count_lines,
        reconcile_daily_learning_truth,
    )

    missing = Path('definitely-missing-learning-52q-r4.jsonl')
    with patch('backend.trading.daily_learning_truth._learning_path', return_value=missing):
        truth = reconcile_daily_learning_truth(
            session_date=DAY,
            snapshots=[],
            outcomes=[],
            learning_records=None,
            mutations=[_resolve_marker(inserted=0)],
        )
    if truth.get('learning_store_status') != 'missing':
        return _fail(str(truth.get('learning_store_status')))
    if truth.get('eligible_learning_samples_added_today') != 0:
        return _fail('missing first-run store may prove daily zero')
    if truth.get('eligible_learning_samples_total') != 0:
        return _fail('missing first-run store may report historical zero')
    lines = '\n'.join(format_learning_sample_count_lines(truth))
    if 'Eligible learning samples added today: 0' not in lines:
        return _fail(lines)
    if 'Total eligible historical samples: 0' not in lines:
        return _fail(lines)
    return 0


def test_valid_zero_plus_malformed_marker_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            _resolve_marker(inserted=0, resolve_id='good-zero'),
            {
                'event': 'resolve_complete',
                'session_date': DAY,
                'inserted': 'bad',
                'deduplicated': 0,
                'sample_ids': [],
                'resolve_id': 'bad-marker',
                'provenance_complete': True,
            },
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('malformed marker must invalidate even with valid zero marker')
    return 0


def test_valid_marker_plus_incomplete_marker_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            _resolve_marker(inserted=0, resolve_id='good-zero'),
            {
                'event': 'resolve_complete',
                'session_date': DAY,
                'inserted': 0,
                'deduplicated': 0,
                'sample_ids': [],
                'resolve_id': 'incomplete',
                'provenance_complete': False,
            },
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('incomplete marker must invalidate provenance')
    return 0


def test_negative_marker_count_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            _resolve_marker(inserted=0, resolve_id='good-zero'),
            {
                'event': 'resolve_complete',
                'session_date': DAY,
                'inserted': -1,
                'deduplicated': 0,
                'sample_ids': [],
                'resolve_id': 'neg',
                'provenance_complete': True,
            },
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('negative marker count must be unavailable')
    return 0


def test_non_list_sample_ids_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            _resolve_marker(inserted=0, resolve_id='good-zero'),
            {
                'event': 'resolve_complete',
                'session_date': DAY,
                'inserted': 0,
                'deduplicated': 0,
                'sample_ids': {'a': 1},
                'resolve_id': 'bad-ids',
                'provenance_complete': True,
            },
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('non-list sample_ids must be unavailable')
    return 0


def test_modern_marker_missing_resolve_id_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            {
                'event': 'resolve_complete',
                'session_date': DAY,
                'inserted': 1,
                'deduplicated': 0,
                'sample_ids': ['sid-x'],
                'provenance_complete': True,
            },
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('positive insert without resolve_id must be unavailable')
    return 0


def test_fractional_inserted_marker_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            {
                'event': 'resolve_complete',
                'session_date': DAY,
                'inserted': 1.2,
                'deduplicated': 0,
                'sample_ids': [],
                'resolve_id': 'frac',
                'provenance_complete': True,
            },
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('fractional inserted must be unavailable')
    return 0


def test_fractional_deduplicated_marker_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            {
                'event': 'resolve_complete',
                'session_date': DAY,
                'inserted': 0,
                'deduplicated': '1.5',
                'sample_ids': [],
                'resolve_id': 'frac-dedupe',
                'provenance_complete': True,
            },
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('fractional deduplicated must be unavailable')
    return 0


def test_boolean_marker_count_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[],
        mutations=[
            {
                'event': 'resolve_complete',
                'session_date': DAY,
                'inserted': True,
                'deduplicated': False,
                'sample_ids': [],
                'resolve_id': 'bool-counts',
                'provenance_complete': True,
            },
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('boolean marker counts must be unavailable')
    return 0


def test_writer_rejects_fractional_counts() -> int:
    from backend.trading.daily_learning_truth import record_learning_resolve_provenance

    try:
        record_learning_resolve_provenance(
            session_date=DAY,
            inserted=1.2,
            deduplicated=0,
            sample_ids=[],
            resolve_id='writer-frac',
            path=Path('__never_write_52q__.jsonl'),
        )
    except ValueError:
        return 0
    return _fail('writer must reject fractional inserted')


def test_writer_rejects_inserted_sample_id_mismatch() -> int:
    from backend.trading.daily_learning_truth import record_learning_resolve_provenance

    try:
        record_learning_resolve_provenance(
            session_date=DAY,
            inserted=2,
            deduplicated=0,
            sample_ids=['only-one'],
            resolve_id='writer-mismatch',
            path=Path('__never_write_52q__.jsonl'),
        )
    except ValueError:
        return 0
    return _fail('writer must reject inserted/sample_ids mismatch')


def test_distinct_resolve_ids_claiming_same_sample_unavailable() -> int:
    from backend.trading.daily_learning_truth import (
        learning_record_dedupe_key,
        reconcile_daily_learning_truth,
    )

    row = _learning_row(symbol='SHARED', session_date=DAY)
    key = learning_record_dedupe_key(row)
    sid = row['sample_id']
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[
            _insert_event(sample_id=sid, symbol='SHARED', dedupe_key=key),
            _resolve_marker(inserted=1, sample_ids=[sid], resolve_id='pass-a'),
            _resolve_marker(inserted=1, sample_ids=[sid], resolve_id='pass-b'),
        ],
    )
    if truth['daily_added_provenance_available']:
        return _fail('same sample under two resolve IDs must be unavailable')
    return 0


def test_distinct_resolve_ids_with_disjoint_samples_total_two() -> int:
    return test_two_legitimate_resolve_passes_total_two()


def test_exact_duplicate_same_resolve_id_remains_idempotent() -> int:
    return test_duplicate_resolve_markers_do_not_inflate()


def test_same_session_missing_recorded_at_zero_marker_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    row = _learning_row(symbol='NOREC', session_date=DAY)
    row.pop('recorded_at', None)
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[_resolve_marker(inserted=0, resolve_id='zero-norec')],
    )
    if truth['daily_added_provenance_available'] or truth['eligible_learning_samples_added_today'] is not None:
        return _fail('same-session missing recorded_at must be unavailable')
    return 0


def test_same_session_malformed_recorded_at_zero_marker_unavailable() -> int:
    from backend.trading.daily_learning_truth import reconcile_daily_learning_truth

    row = _learning_row(symbol='BADREC', session_date=DAY, recorded_at='not-a-date')
    truth = reconcile_daily_learning_truth(
        session_date=DAY,
        snapshots=[],
        outcomes=[],
        learning_records=[row],
        mutations=[_resolve_marker(inserted=0, resolve_id='zero-badrec')],
    )
    if truth['daily_added_provenance_available']:
        return _fail('same-session malformed recorded_at must be unavailable')
    return 0


def main() -> int:
    checks = (
        test_build_is_exactly_52q,
        test_build_pair_mismatches_rejected_52q,
        test_nilkamal_captured_only_not_winner,
        test_outcome_only_win_without_persisted_snapshot_rejected,
        test_snapshot_outcome_ticker_mismatch_rejected,
        test_snapshot_id_mismatch_rejected,
        test_snapshot_session_mismatch_rejected,
        test_outcome_session_mismatch_rejected,
        test_valid_matching_snapshot_and_win_accepted,
        test_canonical_lost_not_winner,
        test_unresolved_quality_not_winner_or_sample,
        test_watch_only_pullback_excluded,
        test_reference_only_excluded,
        test_orphan_insert_event_does_not_count,
        test_marker_says_one_without_persisted_record_unavailable,
        test_matching_event_record_and_marker_count_once,
        test_duplicate_insert_events_count_once,
        test_wrong_event_type_provenance_complete_does_not_prove_zero,
        test_malformed_inserted_marker_does_not_prove_count,
        test_duplicate_resolve_markers_do_not_inflate,
        test_stable_legacy_modern_dedupe,
        test_historical_total_12_with_proven_zero_today,
        test_historical_total_12_without_provenance_unavailable,
        test_session_mismatch_yesterday_not_today,
        test_malformed_numeric_payloads_safe,
        test_historical_report_uses_own_session_date,
        test_unreadable_learning_file_total_unavailable,
        test_formatter_exception_renders_unavailable_not_zero,
        test_valid_empty_and_injected_zero,
        test_duplicate_snapshots_outcomes_do_not_inflate,
        test_decision_trace_cannot_create_winner,
        test_malformed_summary_fields_safe,
        test_import_failure_fallback_no_unbound,
        test_read_only_rendering_guards,
        test_old_daily_review_render_compatible,
        test_validator_is_read_only,
        test_two_legitimate_resolve_passes_total_two,
        test_idempotent_second_pass_does_not_inflate,
        test_duplicate_same_resolve_id_does_not_inflate,
        test_conflicting_same_resolve_id_unavailable,
        test_marker_inserted_must_equal_unique_sample_ids,
        test_ambiguous_multiple_legacy_markers_unavailable,
        test_event_key_and_sample_id_must_match_same_record,
        test_event_symbol_mismatch_unavailable,
        test_unknown_supplied_sample_id_not_ignored,
        test_unknown_supplied_dedupe_key_not_ignored,
        test_same_day_orphan_store_zero_marker_unavailable,
        test_historical_same_session_other_recorded_at_not_today,
        test_malformed_learning_jsonl_historical_unavailable,
        test_malformed_snapshot_outcome_reason_sections_unavailable,
        test_malformed_mutation_jsonl_daily_unavailable,
        test_missing_first_run_learning_file_total_zero,
        test_snapshot_store_failure_reason_sections_unavailable,
        test_outcome_store_failure_reason_sections_unavailable,
        test_source_failure_never_renders_none_recorded_today,
        test_failed_injected_truth_hides_stale_numbers,
        test_legacy_requires_stage_version,
        test_quality_tracked_requires_snapshot_id,
        test_orphan_both_unknown_with_zero_marker_unavailable,
        test_missing_event_identities_with_zero_marker_unavailable,
        test_only_unknown_key_with_zero_marker_unavailable,
        test_only_unknown_sample_id_with_zero_marker_unavailable,
        test_ineligible_persisted_record_event_unavailable,
        test_historical_candidate_only_excluded,
        test_historical_captured_only_excluded,
        test_historical_string_truthy_flags_excluded,
        test_historical_false_string_flag_not_truthy,
        test_accepted_legacy_stage_version_remains_eligible,
        test_arbitrary_legacy_stage_version_excluded,
        test_legacy_candidate_only_excluded,
        test_outcome_without_canonical_id_not_counted,
        test_two_symbol_only_outcomes_do_not_collapse,
        test_duplicate_noncanonical_outcomes_dedupe_deterministically,
        test_noncanonical_win_never_creates_winner_reason,
        test_repeated_reconciliation_is_byte_deterministic,
        test_missing_reason_availability_preserves_counts,
        test_malformed_reason_availability_never_none_recorded,
        test_winner_missing_state_rejected,
        test_winner_unknown_state_rejected,
        test_historical_missing_state_excluded,
        test_historical_unknown_state_excluded,
        test_quality_tracked_unknown_state_excluded,
        test_genuine_writer_state_remains_eligible,
        test_unreadable_learning_store_daily_and_total_unavailable,
        test_malformed_learning_store_daily_and_total_unavailable,
        test_zero_marker_cannot_override_unreadable_learning_store,
        test_missing_first_run_store_still_allows_proven_zero,
        test_valid_zero_plus_malformed_marker_unavailable,
        test_valid_marker_plus_incomplete_marker_unavailable,
        test_negative_marker_count_unavailable,
        test_non_list_sample_ids_unavailable,
        test_modern_marker_missing_resolve_id_unavailable,
        test_fractional_inserted_marker_unavailable,
        test_fractional_deduplicated_marker_unavailable,
        test_boolean_marker_count_unavailable,
        test_writer_rejects_fractional_counts,
        test_writer_rejects_inserted_sample_id_mismatch,
        test_distinct_resolve_ids_claiming_same_sample_unavailable,
        test_distinct_resolve_ids_with_disjoint_samples_total_two,
        test_exact_duplicate_same_resolve_id_remains_idempotent,
        test_same_session_missing_recorded_at_zero_marker_unavailable,
        test_same_session_malformed_recorded_at_zero_marker_unavailable,
    )
    for check in checks:
        err = check()
        if err:
            return err
        print(f'PASS: {check.__name__}', flush=True)
    print('DAILY_REVIEW_LEARNING_TRUTH_52Q_PASS', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
