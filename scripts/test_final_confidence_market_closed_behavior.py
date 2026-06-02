#!/usr/bin/env python3
"""
Test final confidence behavior in RESEARCH_MODE / market closed.

Usage:
  python scripts/test_final_confidence_market_closed_behavior.py

Prints exactly FINAL_CONFIDENCE_MARKET_CLOSED_OK on success.
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
    print(f'FINAL_CONFIDENCE_MARKET_CLOSED_FAIL: {msg}', file=sys.stderr)
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


def _research_ctx(**overrides: object) -> dict:
    base = {
        'latest_prices': {},
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
            'warnings': ['market_closed', 'runtime_snapshot_stale', 'news_feed_stale'],
        },
        'market_closed': True,
    }
    base.update(overrides)
    return base


def main() -> int:
    from backend.analytics.final_confidence_fusion import score_candidate

    strong = score_candidate({
        'ticker': 'MOCKSTRONG',
        'prediction_id': 'mock:strong_research',
        'direction': 'BUY',
        'confidence_label': 'HIGH',
        'signal_stack': {'entry_price': 98.0, 'target_price': 105.0, 'stop_loss': 95.0},
    }, context=_research_ctx(latest_prices={'MOCKSTRONG': 100.0}))

    if strong.get('decision') != 'WATCH':
        return _fail(f'strong research candidate expected WATCH, got {strong.get("decision")}')
    if strong.get('decision') == 'NO_DECISION':
        return _fail('strong research candidate must not be NO_DECISION')
    warnings = strong.get('warnings') or []
    if 'market_closed_buy_capped_to_watch' not in warnings:
        return _fail('expected market_closed_buy_capped_to_watch warning')

    risk = score_candidate({
        'ticker': 'MOCKAVOID',
        'prediction_id': 'mock:avoid_research',
        'direction': 'BUY',
        'confidence_label': 'LOW',
    }, context=_research_ctx(
        latest_prices={'MOCKAVOID': 50.0},
        advise_prediction=lambda _c: _mock_advice('avoid_candidate', 22, sample_size=8),
        broker_intelligence_fn=lambda _t: {
            'pick_count': 1,
            'our_vs_broker': {'relationship': 'conflict'},
        },
        historical_fn=lambda _t: {'overall': {'wins': 1, 'losses': 9, 'win_rate': 0.1}},
    ))
    if risk.get('decision') != 'AVOID':
        return _fail(f'risk research candidate expected AVOID, got {risk.get("decision")}')

    missing = score_candidate({'prediction_id': 'mock:missing_ticker'})
    if missing.get('decision') != 'NO_DECISION':
        return _fail('missing ticker must be NO_DECISION')
    if 'missing_ticker' not in (missing.get('hard_warnings') or []):
        return _fail('missing ticker hard warning expected')

    suspicious = score_candidate({
        'ticker': 'MOCKPRICE',
        'prediction_id': 'mock:bad_price',
        'direction': 'BUY',
        'signal_stack': {
            'entry_price': 100.0,
            'latest_price': 500.0,
            'target_price': 110.0,
            'stop_loss': 95.0,
        },
    }, context=_research_ctx(
        latest_prices={'MOCKPRICE': 500.0},
        advise_prediction=lambda _c: _mock_advice('neutral', 50),
        broker_intelligence_fn=lambda _t: {'pick_count': 0, 'our_vs_broker': {'relationship': 'unclear'}},
        historical_fn=lambda _t: {'overall': {'wins': 0, 'losses': 0, 'win_rate': None}},
    ))
    if suspicious.get('decision') not in {'NO_DECISION', 'AVOID'}:
        return _fail(f'suspicious price expected NO_DECISION or AVOID, got {suspicious.get("decision")}')
    if 'suspicious_price_scale' not in (suspicious.get('hard_warnings') or []):
        return _fail('suspicious_price_scale hard warning expected')

    open_buy = score_candidate({
        'ticker': 'MOCKOPEN',
        'prediction_id': 'mock:open_buy',
        'direction': 'BUY',
        'confidence_label': 'HIGH',
        'signal_stack': {'entry_price': 98.0, 'target_price': 105.0, 'stop_loss': 95.0},
    }, context={
        'latest_prices': {'MOCKOPEN': 100.0},
        'advise_prediction': lambda _c: _mock_advice('boost', 78),
        'broker_intelligence_fn': lambda _t: {
            'pick_count': 2,
            'our_vs_broker': {'relationship': 'agreement'},
        },
        'historical_fn': lambda _t: {'overall': {'wins': 8, 'losses': 2, 'win_rate': 0.8}},
        'router_fn': lambda: {
            'active_mode': 'INDIA_MODE',
            'india_session': 'regular',
            'usa_session': 'closed',
            'warnings': [],
        },
        'freshness_fn': lambda: {'safe_to_use': True, 'market_closed': False, 'warnings': []},
        'market_closed': False,
    })
    if open_buy.get('decision') != 'BUY_CANDIDATE':
        return _fail(f'open-market strong candidate expected BUY_CANDIDATE, got {open_buy.get("decision")}')

    print('FINAL_CONFIDENCE_MARKET_CLOSED_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
