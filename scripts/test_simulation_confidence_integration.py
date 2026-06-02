#!/usr/bin/env python3
"""
Integration tests for historical simulation in final confidence fusion.

Usage:
  python scripts/test_simulation_confidence_integration.py

Prints exactly SIMULATION_CONFIDENCE_INTEGRATION_OK on success.
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
    print(f'SIMULATION_CONFIDENCE_INTEGRATION_FAIL: {msg}', file=sys.stderr)
    return 1


def _mock_advice(overall: str = 'neutral', learning_score: int = 50) -> dict:
    return {
        'overall_advice': overall,
        'learning_score': learning_score,
        'sample_size': 10,
        'warnings': [],
        'reasons': [],
        'components': {},
    }


def _positive_sim(_candidate: dict) -> dict:
    return {
        'ok': True,
        'ticker': 'MOCKPOS',
        'inferred_strategy': 'momentum_breakout_20',
        'strategy_sample': 120,
        'strategy_win_rate': 0.52,
        'strategy_expectancy_pct': 1.2,
        'ticker_sample': 25,
        'ticker_win_rate': 0.5,
        'confidence_adjustment': 3,
        'warnings': [],
        'reasons': ['positive strategy'],
    }


def _bearish_negative_sim(_candidate: dict) -> dict:
    return {
        'ok': True,
        'ticker': 'MOCKBEAR',
        'inferred_strategy': 'bearish_breakdown_20',
        'strategy_sample': 80,
        'strategy_win_rate': 0.38,
        'strategy_expectancy_pct': -0.8,
        'ticker_sample': 5,
        'ticker_win_rate': None,
        'confidence_adjustment': -6,
        'warnings': [],
        'reasons': ['weak bearish strategy'],
    }


def _low_sample_sim(_candidate: dict) -> dict:
    return {
        'ok': True,
        'ticker': 'MOCKLOW',
        'inferred_strategy': 'momentum_breakout_20',
        'strategy_sample': 12,
        'strategy_win_rate': 0.6,
        'strategy_expectancy_pct': 2.0,
        'ticker_sample': 0,
        'ticker_win_rate': None,
        'confidence_adjustment': 0,
        'warnings': ['low_simulation_sample'],
        'reasons': ['low sample'],
    }


def _unknown_capped_sim(_candidate: dict) -> dict:
    return {
        'ok': True,
        'ticker': 'MOCKUNK',
        'inferred_strategy': 'UNKNOWN',
        'strategy_sample': 200,
        'strategy_win_rate': 0.55,
        'strategy_expectancy_pct': 5.0,
        'ticker_sample': 0,
        'ticker_win_rate': None,
        'confidence_adjustment': 2,
        'warnings': [],
        'reasons': ['unknown capped'],
    }


def _neutral_ctx(**overrides: object) -> dict:
    base = {
        'latest_prices': {},
        'advise_prediction': lambda _c: _mock_advice(),
        'broker_intelligence_fn': lambda _t: {'pick_count': 0, 'our_vs_broker': {'relationship': 'unclear'}},
        'historical_fn': lambda _t: {'overall': {'wins': 0, 'losses': 0, 'win_rate': None}},
        'router_fn': lambda: {'active_mode': 'INDIA_MODE', 'warnings': []},
        'freshness_fn': lambda: {'safe_to_use': True, 'warnings': []},
        'load_calibration': False,
    }
    base.update(overrides)
    return base


def main() -> int:
    from backend.analytics.final_confidence_fusion import score_candidate
    from backend.analytics.simulation_performance_adapter import SIMULATION_ADJUSTMENT_CAP

    positive = score_candidate({
        'ticker': 'MOCKPOS',
        'prediction_id': 'mock:sim_pos',
        'direction': 'BUY',
        'signal_type': 'breakout',
        'confidence_label': 'MEDIUM',
    }, context=_neutral_ctx(simulation_fn=_positive_sim))
    sim_adj = int(positive.get('simulation_adjustment') or 0)
    if sim_adj <= 0 or sim_adj > SIMULATION_ADJUSTMENT_CAP:
        return _fail(f'positive strategy expected small positive adj, got {sim_adj}')
    if positive.get('adjustments', {}).get('H_historical_simulation') != sim_adj:
        return _fail('H_historical_simulation adjustment mismatch')

    bearish = score_candidate({
        'ticker': 'MOCKBEAR',
        'prediction_id': 'mock:sim_bear',
        'direction': 'BEARISH',
        'category': 'breakdown',
        'confidence_label': 'LOW',
    }, context=_neutral_ctx(simulation_fn=_bearish_negative_sim))
    if int(bearish.get('simulation_adjustment') or 0) >= 0:
        return _fail('bearish negative expectancy must apply negative adjustment')

    low = score_candidate({
        'ticker': 'MOCKLOW',
        'prediction_id': 'mock:sim_low',
        'direction': 'BUY',
        'signal_type': 'breakout',
    }, context=_neutral_ctx(simulation_fn=_low_sample_sim))
    if int(low.get('simulation_adjustment') or 0) != 0:
        return _fail('low sample must not adjust score')
    if 'low_simulation_sample' not in (low.get('warnings') or []):
        return _fail('low_simulation_sample warning expected')

    unknown = score_candidate({
        'ticker': 'MOCKUNK',
        'prediction_id': 'mock:sim_unk',
        'direction': 'NEUTRAL',
    }, context=_neutral_ctx(simulation_fn=_unknown_capped_sim))
    unk_adj = int(unknown.get('simulation_adjustment') or 0)
    if abs(unk_adj) > 2:
        return _fail(f'UNKNOWN strategy adj must be capped at +/-2, got {unk_adj}')

    closed = score_candidate({
        'ticker': 'MOCKCLOSED',
        'prediction_id': 'mock:sim_closed',
        'direction': 'BUY',
        'confidence_label': 'HIGH',
        'signal_stack': {'entry_price': 100.0, 'target_price': 110.0, 'stop_loss': 95.0},
    }, context={
        'latest_prices': {'MOCKCLOSED': 100.0},
        'advise_prediction': lambda _c: _mock_advice('boost', 80),
        'broker_intelligence_fn': lambda _t: {
            'pick_count': 2,
            'our_vs_broker': {'relationship': 'agreement'},
        },
        'historical_fn': lambda _t: {'overall': {'wins': 8, 'losses': 2, 'win_rate': 0.8}},
        'simulation_fn': _positive_sim,
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
    })
    if closed.get('decision') == 'BUY_CANDIDATE':
        return _fail('RESEARCH_MODE / market closed must not emit BUY_CANDIDATE')

    avoid_sim = lambda _c: {
        'ok': True,
        'ticker': 'MOCKAVOID',
        'inferred_strategy': 'momentum_breakout_20',
        'strategy_sample': 100,
        'strategy_win_rate': 0.55,
        'strategy_expectancy_pct': 2.0,
        'ticker_sample': 30,
        'ticker_win_rate': 0.5,
        'confidence_adjustment': 8,
        'warnings': [],
        'reasons': ['strong sim push'],
    }
    avoid = score_candidate({
        'ticker': 'MOCKAVOID',
        'prediction_id': 'mock:sim_avoid',
        'direction': 'BUY',
        'confidence_label': 'LOW',
    }, context=_neutral_ctx(
        simulation_fn=avoid_sim,
        advise_prediction=lambda _c: _mock_advice('avoid_candidate', 22),
        broker_intelligence_fn=lambda _t: {
            'pick_count': 1,
            'our_vs_broker': {'relationship': 'conflict'},
        },
        historical_fn=lambda _t: {'overall': {'wins': 1, 'losses': 9, 'win_rate': 0.1}},
        router_fn=lambda: {'active_mode': 'RESEARCH_MODE', 'warnings': []},
        freshness_fn=lambda: {'safe_to_use': False, 'warnings': ['runtime_snapshot_stale']},
    ))
    if avoid.get('decision') == 'BUY_CANDIDATE':
        return _fail('AVOID must not become BUY_CANDIDATE from simulation alone')
    if 'simulation_avoid_buy_blocked' in (avoid.get('warnings') or []):
        pass
    elif int(avoid.get('simulation_adjustment') or 0) > 0 and avoid.get('decision') != 'BUY_CANDIDATE':
        pass
    else:
        breakdown = avoid.get('score_breakdown') or []
        hist = [b for b in breakdown if b.get('component') == 'historical_simulation']
        if not hist:
            return _fail('score_breakdown should include historical_simulation when sim applies')

    print('SIMULATION_CONFIDENCE_INTEGRATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
