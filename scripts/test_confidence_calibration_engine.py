#!/usr/bin/env python3
"""
Unit tests for confidence calibration engine (mock data, no DB mutation).

Usage:
  python scripts/test_confidence_calibration_engine.py

Prints exactly CONFIDENCE_CALIBRATION_ENGINE_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'CONFIDENCE_CALIBRATION_ENGINE_FAIL: {msg}', file=sys.stderr)
    return 1


def _mock_rows() -> list[dict]:
    rows: list[dict] = []
    # Overconfident bucket 70-79: high scores, low win rate
    for index in range(12):
        rows.append({
            'prediction_id': f'mock:over:{index}',
            'ticker': 'MOCKOVER',
            'final_score': 75,
            'decision': 'BUY_CANDIDATE',
            'warnings': ['low_sample_size'] if index < 3 else [],
            'hard_warnings': [],
        })
    # Underconfident bucket 30-39: low scores, high win rate
    for index in range(12):
        rows.append({
            'prediction_id': f'mock:under:{index}',
            'ticker': 'MOCKUNDER',
            'final_score': 35,
            'decision': 'WATCH',
            'warnings': [],
            'hard_warnings': [],
        })
    # Low sample bucket 50-59
    for index in range(5):
        rows.append({
            'prediction_id': f'mock:low:{index}',
            'ticker': 'MOCKLOW',
            'final_score': 55,
            'decision': 'WATCH',
            'warnings': ['stale_critical_sources'],
            'hard_warnings': [],
        })
    return rows


def _mock_live_outcomes() -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for index in range(12):
        outcomes[f'mock:over:{index}'] = 'LOSS' if index < 9 else 'WIN'
    for index in range(12):
        outcomes[f'mock:under:{index}'] = 'WIN' if index < 9 else 'LOSS'
    for index in range(5):
        outcomes[f'mock:low:{index}'] = 'WIN' if index % 2 == 0 else 'LOSS'
    return outcomes


def _mock_historical_outcomes() -> dict[str, str]:
    return {}


def main() -> int:
    import backend.analytics.confidence_calibration_engine as engine

    rows = _mock_rows()
    live = _mock_live_outcomes()
    enriched = engine._enrich_rows(rows, live_outcomes=live, historical_outcomes=_mock_historical_outcomes())

    buckets = engine._build_buckets_for_rows(enriched, mode='live')
    if len(buckets) != 10:
        return _fail(f'expected 10 buckets, got {len(buckets)}')

    over_bucket = next(item for item in buckets if item['bucket'] == '70-79')
    if over_bucket['sample_warning'] != 'ok':
        return _fail('70-79 bucket should have ok sample')
    if over_bucket['expected_win_rate'] is None:
        return _fail('expected_win_rate missing for 70-79 bucket')
    expected = over_bucket['avg_score'] / 100
    if abs(over_bucket['expected_win_rate'] - expected) > 0.001:
        return _fail('expected_win_rate must equal avg_score / 100')
    if over_bucket['calibration_error'] is None:
        return _fail('calibration_error missing for 70-79 bucket')
    if over_bucket['calibration_error'] >= engine.OVERCONFIDENT_ERROR:
        return _fail('70-79 bucket should be overconfident')

    low_bucket = next(item for item in buckets if item['bucket'] == '50-59')
    if low_bucket['sample_warning'] != 'low_sample':
        return _fail('50-59 bucket must be low_sample')

    under_bucket = next(item for item in buckets if item['bucket'] == '30-39')
    if under_bucket['calibration_error'] <= engine.UNDERCONFIDENT_ERROR:
        return _fail('30-39 bucket should be underconfident')

    over = engine.identify_overconfident_buckets(buckets=buckets, mode='live')
    if over.get('count', 0) < 1:
        return _fail('expected at least one overconfident bucket')

    under = engine.identify_underconfident_buckets(buckets=buckets, mode='live')
    if under.get('count', 0) < 1:
        return _fail('expected at least one underconfident bucket')

    recs = engine.recommend_score_adjustments(mode='live', buckets=buckets)
    recommendations = recs.get('recommendations') or []
    if not recommendations:
        return _fail('expected recommendations')
    for rec in recommendations:
        if rec.get('type') == 'reduce_score' and int(rec.get('sample_size') or 0) >= 10:
            if rec.get('strength') not in ('weak', 'medium', 'strong'):
                return _fail('invalid recommendation strength')

    low_sample_recs = [
        rec for rec in recommendations
        if int(rec.get('sample_size') or 0) < 10 and rec.get('strength') in ('medium', 'strong')
    ]
    if low_sample_recs:
        return _fail('low sample buckets must not get medium/strong score recommendations')

    print('CONFIDENCE_CALIBRATION_ENGINE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
