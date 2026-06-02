#!/usr/bin/env python3
"""
Test soft calibration adjustment on final confidence fusion.

Usage:
  python scripts/test_final_confidence_calibration_adjustment.py

Prints exactly FINAL_CONFIDENCE_CALIBRATION_ADJUSTMENT_OK on success.
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
    print(f'FINAL_CONFIDENCE_CALIBRATION_ADJUSTMENT_FAIL: {msg}', file=sys.stderr)
    return 1


def _mock_advice(overall: str, learning_score: int, sample_size: int = 10) -> dict:
    return {
        'overall_advice': overall,
        'learning_score': learning_score,
        'sample_size': sample_size,
        'warnings': [],
        'reasons': [f'mock {overall}'],
        'components': {},
    }


def _mock_calibration_report(
    bucket: str,
    rec_type: str,
    strength: str,
    *,
    sample_size: int = 25,
    sample_warning: str = 'ok',
) -> dict:
    return {
        'ok': True,
        'combined': {
            'buckets': [
                {
                    'bucket': bucket,
                    'sample_warning': sample_warning,
                    'wins': sample_size // 2,
                    'losses': sample_size // 2,
                },
            ],
        },
        'recommendations': [
            {
                'bucket': bucket,
                'type': rec_type,
                'strength': strength,
                'sample_size': sample_size,
                'calibration_error': 0.2,
            },
        ],
    }


def _neutral_ctx(**overrides: object) -> dict:
    base = {
        'latest_prices': {},
        'advise_prediction': lambda _c: _mock_advice('neutral', 50),
        'broker_intelligence_fn': lambda _t: {'pick_count': 0, 'our_vs_broker': {'relationship': 'unclear'}},
        'historical_fn': lambda _t: {'overall': {'wins': 0, 'losses': 0, 'win_rate': None}},
        'router_fn': lambda: {'active_mode': 'INDIA_MODE', 'warnings': []},
        'freshness_fn': lambda: {'safe_to_use': True, 'warnings': []},
        'load_calibration': False,
    }
    base.update(overrides)
    return base


def main() -> int:
    from backend.analytics.final_confidence_fusion import (
        apply_soft_calibration_adjustment,
        score_candidate,
    )

    weak_report = _mock_calibration_report('50-59', 'increase_score', 'weak')
    weak_result = apply_soft_calibration_adjustment(52, {}, weak_report)
    if weak_result.get('adjusted_score') != 52:
        return _fail(f'weak recommendation must not change score, got {weak_result.get("adjusted_score")}')
    if 'weak_calibration_signal' not in (weak_result.get('soft_warnings') or []):
        return _fail('weak recommendation must add weak_calibration_signal')

    medium_report = _mock_calibration_report('50-59', 'increase_score', 'medium')
    medium_result = apply_soft_calibration_adjustment(52, {}, medium_report)
    if medium_result.get('calibration_adjustment') != 5:
        return _fail(f'medium increase expected +5, got {medium_result.get("calibration_adjustment")}')
    if medium_result.get('adjusted_score') != 57:
        return _fail(f'medium increase expected score 57, got {medium_result.get("adjusted_score")}')

    strong_report = _mock_calibration_report('50-59', 'reduce_score', 'strong')
    strong_result = apply_soft_calibration_adjustment(52, {}, strong_report)
    if strong_result.get('calibration_adjustment') != -10:
        return _fail(f'strong reduce expected -10, got {strong_result.get("calibration_adjustment")}')
    if strong_result.get('adjusted_score') != 42:
        return _fail(f'strong reduce expected score 42, got {strong_result.get("adjusted_score")}')

    weak_scored = score_candidate({
        'ticker': 'MOCKCAL',
        'prediction_id': 'mock:cal_weak',
        'direction': 'BUY',
        'confidence_label': 'MEDIUM',
    }, context=_neutral_ctx(calibration_report=weak_report))
    if int(weak_scored.get('final_score') or 0) != int(weak_scored.get('pre_calibration_score') or 0):
        return _fail('weak calibration must not change final_score in score_candidate')
    if 'weak_calibration_signal' not in (weak_scored.get('warnings') or []):
        return _fail('weak calibration warning missing from score_candidate')

    medium_scored = score_candidate({
        'ticker': 'MOCKCAL2',
        'prediction_id': 'mock:cal_medium',
        'direction': 'BUY',
        'confidence_label': 'MEDIUM',
    }, context=_neutral_ctx(calibration_report=medium_report))
    pre = int(medium_scored.get('pre_calibration_score') or 0)
    post = int(medium_scored.get('final_score') or 0)
    if post - pre != 5:
        return _fail(f'medium calibration expected +5 delta, pre={pre} post={post}')
    breakdown = medium_scored.get('score_breakdown') or []
    cal_parts = [b for b in breakdown if b.get('component') == 'calibration']
    if not cal_parts or cal_parts[0].get('points') != 5:
        return _fail('score_breakdown must include calibration component with +5 points')

    research_ctx = {
        'latest_prices': {'MOCKCAL3': 100.0},
        'advise_prediction': lambda _c: _mock_advice('boost', 78),
        'broker_intelligence_fn': lambda _t: {
            'pick_count': 2,
            'our_vs_broker': {'relationship': 'agreement'},
        },
        'historical_fn': lambda _t: {'overall': {'wins': 8, 'losses': 2, 'win_rate': 0.8}},
        'router_fn': lambda: {
            'active_mode': 'RESEARCH_MODE',
            'india_session': 'closed',
            'usa_session': 'closed',
            'warnings': ['market_closed'],
        },
        'freshness_fn': lambda: {
            'safe_to_use': False,
            'market_closed': True,
            'warnings': ['market_closed'],
        },
        'market_closed': True,
        'load_calibration': False,
        'calibration_report': None,
    }
    closed = score_candidate({
        'ticker': 'MOCKCAL3',
        'prediction_id': 'mock:cal_closed',
        'direction': 'BUY',
        'confidence_label': 'HIGH',
        'signal_stack': {'entry_price': 98.0, 'target_price': 105.0, 'stop_loss': 95.0},
    }, context=research_ctx)
    if closed.get('decision') == 'BUY_CANDIDATE':
        return _fail('RESEARCH_MODE / market closed must not emit BUY_CANDIDATE')
    if closed.get('buy_cap_active') and closed.get('decision') not in {'WATCH', 'AVOID', 'NO_DECISION'}:
        return _fail(f'unexpected decision under buy cap: {closed.get("decision")}')

    high_bucket_report = _mock_calibration_report('60-69', 'increase_score', 'strong', sample_size=30)
    avoid_ctx = _neutral_ctx(
        calibration_report=high_bucket_report,
        advise_prediction=lambda _c: _mock_advice('avoid_candidate', 22, sample_size=8),
        broker_intelligence_fn=lambda _t: {
            'pick_count': 1,
            'our_vs_broker': {'relationship': 'conflict'},
        },
        historical_fn=lambda _t: {'overall': {'wins': 1, 'losses': 9, 'win_rate': 0.1}},
        router_fn=lambda: {'active_mode': 'RESEARCH_MODE', 'warnings': []},
        freshness_fn=lambda: {'safe_to_use': False, 'warnings': ['runtime_snapshot_stale']},
    )
    avoid_scored = score_candidate({
        'ticker': 'MOCKCAL4',
        'prediction_id': 'mock:cal_avoid',
        'direction': 'BUY',
        'confidence_label': 'LOW',
    }, context=avoid_ctx)
    if avoid_scored.get('decision') == 'BUY_CANDIDATE':
        return _fail('AVOID candidate must not become BUY_CANDIDATE from calibration alone')
    if int(avoid_scored.get('pre_calibration_score') or 100) <= 55:
        pre_dec = avoid_scored.get('decision')
        if pre_dec == 'BUY_CANDIDATE':
            return _fail('pre-calibration should not already be BUY for avoid test')

    print('FINAL_CONFIDENCE_CALIBRATION_ADJUSTMENT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
