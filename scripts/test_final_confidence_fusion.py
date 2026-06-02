#!/usr/bin/env python3
"""
Smoke test for final confidence fusion (mock cases, no DB writes).

Usage:
  python scripts/test_final_confidence_fusion.py

Prints exactly FINAL_CONFIDENCE_FUSION_OK on success.
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
    print(f'FINAL_CONFIDENCE_FUSION_FAIL: {msg}', file=sys.stderr)
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


def main() -> int:
    from backend.analytics.final_confidence_fusion import (
        BASE_SCORE,
        VALID_DECISIONS,
        score_candidate,
    )

    strong_ctx = {
        'latest_prices': {'MOCKSTRONG': 100.0},
        'advise_prediction': lambda _c: _mock_advice('boost', 78),
        'broker_intelligence_fn': lambda _t: {
            'pick_count': 2,
            'our_vs_broker': {'relationship': 'agreement'},
        },
        'historical_fn': lambda _t: {'overall': {'wins': 8, 'losses': 2, 'win_rate': 0.8}},
        'router_fn': lambda: {'active_mode': 'INDIA_MODE', 'warnings': []},
        'freshness_fn': lambda: {'safe_to_use': True, 'warnings': []},
    }
    strong = score_candidate({
        'ticker': 'MOCKSTRONG',
        'prediction_id': 'mock:strong',
        'direction': 'BUY',
        'confidence_label': 'HIGH',
        'signal_stack': {'entry_price': 98.0, 'target_price': 105.0, 'stop_loss': 95.0},
    }, context=strong_ctx)
    if strong.get('decision') != 'BUY_CANDIDATE':
        return _fail(f'expected BUY_CANDIDATE, got {strong.get("decision")}')
    if not (70 <= int(strong.get('final_score') or 0) <= 100):
        return _fail(f'strong candidate score out of range: {strong.get("final_score")}')

    avoid_ctx = {
        'latest_prices': {'MOCKAVOID': 50.0},
        'advise_prediction': lambda _c: _mock_advice('avoid_candidate', 22, sample_size=8),
        'broker_intelligence_fn': lambda _t: {
            'pick_count': 1,
            'our_vs_broker': {'relationship': 'conflict'},
        },
        'historical_fn': lambda _t: {'overall': {'wins': 1, 'losses': 9, 'win_rate': 0.1}},
        'router_fn': lambda: {'active_mode': 'RESEARCH_MODE', 'warnings': []},
        'freshness_fn': lambda: {'safe_to_use': False, 'warnings': ['runtime_snapshot_stale', 'news_feed_stale']},
    }
    avoid = score_candidate({
        'ticker': 'MOCKAVOID',
        'prediction_id': 'mock:avoid',
        'direction': 'BUY',
        'confidence_label': 'LOW',
    }, context=avoid_ctx)
    if avoid.get('decision') not in {'AVOID', 'NO_DECISION'}:
        return _fail(f'expected AVOID or NO_DECISION, got {avoid.get("decision")}')
    if int(avoid.get('final_score') or 100) > 55:
        return _fail(f'avoid candidate score too high: {avoid.get("final_score")}')

    missing = score_candidate({'prediction_id': 'mock:missing'})
    if missing.get('decision') != 'NO_DECISION':
        return _fail('missing ticker must be NO_DECISION')
    if 'missing_ticker' not in (missing.get('hard_warnings') or []):
        return _fail('missing ticker hard warning expected')

    price_bad = score_candidate({
        'ticker': 'MOCKPRICE',
        'prediction_id': 'mock:bad_price',
        'direction': 'BUY',
        'signal_stack': {'entry_price': 100.0, 'latest_price': 500.0, 'target_price': 110.0, 'stop_loss': 95.0},
    }, context={
        'latest_prices': {'MOCKPRICE': 500.0},
        'advise_prediction': lambda _c: _mock_advice('neutral', 50),
        'broker_intelligence_fn': lambda _t: {'pick_count': 0, 'our_vs_broker': {'relationship': 'unclear'}},
        'historical_fn': lambda _t: {'overall': {'wins': 0, 'losses': 0, 'win_rate': None}},
        'router_fn': lambda: {'active_mode': 'INDIA_MODE', 'warnings': []},
        'freshness_fn': lambda: {'safe_to_use': True, 'warnings': []},
    })
    if price_bad.get('decision') not in {'NO_DECISION', 'AVOID'}:
        return _fail(f'suspicious price scale must force NO_DECISION or AVOID, got {price_bad.get("decision")}')
    if 'suspicious_price_scale' not in (price_bad.get('hard_warnings') or []):
        return _fail('suspicious_price_scale hard warning expected')

    watch = score_candidate({
        'ticker': 'MOCKWATCH',
        'prediction_id': 'mock:watch',
        'direction': 'BUY',
        'confidence_label': 'MEDIUM',
    }, context={
        'latest_prices': {},
        'advise_prediction': lambda _c: _mock_advice('neutral', 52),
        'broker_intelligence_fn': lambda _t: {'pick_count': 0, 'our_vs_broker': {'relationship': 'unclear'}},
        'historical_fn': lambda _t: {'overall': {'wins': 2, 'losses': 2, 'win_rate': 0.5}},
        'router_fn': lambda: {'active_mode': 'RESEARCH_MODE', 'warnings': []},
        'freshness_fn': lambda: {'safe_to_use': True, 'warnings': []},
    })
    if watch.get('decision') != 'WATCH':
        return _fail(f'expected WATCH, got {watch.get("decision")}')

    for key in (
        'final_score', 'decision', 'base_score', 'adjustments', 'total_adjustment',
        'hard_warnings', 'warnings', 'explanations', 'shadow_mode', 'disclaimer',
    ):
        if key not in strong:
            return _fail(f'missing output key: {key}')

    if strong.get('base_score') != BASE_SCORE:
        return _fail('base_score must be 50')
    if str(strong.get('decision')) not in VALID_DECISIONS:
        return _fail('invalid decision token')
    if strong.get('shadow_mode') is not True:
        return _fail('shadow_mode must be true')

    adj = strong.get('adjustments') or {}
    for letter in (
        'A_memory_advisor', 'B_broker_consensus', 'C_broker_intelligence',
        'D_historical_learning', 'E_market_router', 'F_source_freshness', 'G_price_sanity',
    ):
        if letter not in adj:
            return _fail(f'missing adjustment key: {letter}')

    print('FINAL_CONFIDENCE_FUSION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
