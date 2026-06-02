#!/usr/bin/env python3
"""
Validate final confidence report includes historical simulation integration.

Usage:
  python scripts/generate_final_confidence_report.py
  python scripts/validate_final_confidence_simulation_integration.py

Prints exactly FINAL_CONFIDENCE_SIMULATION_INTEGRATION_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / 'data' / 'final_confidence_report.json'

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'FINAL_CONFIDENCE_SIMULATION_INTEGRATION_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.final_confidence_fusion import (
        ADJUSTMENT_CAPS,
        build_final_confidence_report,
        score_candidate,
    )
    from backend.analytics.simulation_performance_adapter import SIMULATION_ADJUSTMENT_CAP

    report = build_final_confidence_report(limit=5)
    if report.get('ok') is not True:
        return _fail('build_final_confidence_report failed')

    simulation = report.get('simulation')
    if not isinstance(simulation, dict):
        return _fail('report missing simulation section')
    for key in (
        'simulation_applied',
        'simulation_positive',
        'simulation_negative',
        'simulation_neutral',
    ):
        if key not in simulation:
            return _fail(f'simulation section missing {key}')

    if REPORT_PATH.is_file():
        disk = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
        if 'simulation' not in disk:
            return _fail('final_confidence_report.json missing simulation section')

    rows = report.get('rows') or []
    if rows:
        row = rows[0]
        if 'historical_simulation' not in row and 'simulation_adjustment' not in row:
            return _fail('row missing historical_simulation / simulation_adjustment')

    scored = score_candidate({
        'ticker': 'SIMVAL',
        'prediction_id': 'mock:sim_val',
        'direction': 'BUY',
        'signal_type': 'breakout',
    }, context={
        'latest_prices': {},
        'advise_prediction': lambda _c: {
            'overall_advice': 'neutral',
            'learning_score': 50,
            'sample_size': 5,
            'warnings': [],
            'reasons': [],
            'components': {},
        },
        'broker_intelligence_fn': lambda _t: {'pick_count': 0, 'our_vs_broker': {'relationship': 'unclear'}},
        'historical_fn': lambda _t: {'overall': {'wins': 0, 'losses': 0, 'win_rate': None}},
        'simulation_fn': lambda _c: {
            'ok': True,
            'inferred_strategy': 'momentum_breakout_20',
            'confidence_adjustment': 99,
            'warnings': [],
            'reasons': ['cap test'],
        },
        'router_fn': lambda: {'active_mode': 'RESEARCH_MODE', 'warnings': []},
        'freshness_fn': lambda: {'safe_to_use': True, 'warnings': []},
        'load_calibration': False,
    })
    cap = ADJUSTMENT_CAPS.get('H_historical_simulation', SIMULATION_ADJUSTMENT_CAP)
    if abs(int(scored.get('simulation_adjustment') or 0)) > cap:
        return _fail(f'simulation adjustment exceeds cap {cap}')
    if 'historical_simulation' not in scored:
        return _fail('score_candidate missing historical_simulation')

    breakdown = scored.get('score_breakdown') or []
    if not any(b.get('component') == 'historical_simulation' for b in breakdown):
        return _fail('score_breakdown missing historical_simulation component')

    research = score_candidate({
        'ticker': 'SIMRES',
        'prediction_id': 'mock:sim_res',
        'direction': 'BUY',
        'confidence_label': 'HIGH',
        'signal_stack': {'entry_price': 100.0, 'target_price': 120.0, 'stop_loss': 90.0},
    }, context={
        'latest_prices': {'SIMRES': 100.0},
        'advise_prediction': lambda _c: {
            'overall_advice': 'boost',
            'learning_score': 85,
            'sample_size': 20,
            'warnings': [],
            'reasons': [],
            'components': {},
        },
        'broker_intelligence_fn': lambda _t: {
            'pick_count': 3,
            'our_vs_broker': {'relationship': 'agreement'},
        },
        'historical_fn': lambda _t: {'overall': {'wins': 10, 'losses': 2, 'win_rate': 0.83}},
        'simulation_fn': lambda _c: {
            'ok': True,
            'confidence_adjustment': 10,
            'warnings': [],
            'reasons': [],
        },
        'router_fn': lambda: {
            'active_mode': 'RESEARCH_MODE',
            'india_session': 'closed',
            'usa_session': 'closed',
        },
        'freshness_fn': lambda: {'safe_to_use': True, 'market_closed': True, 'warnings': []},
        'market_closed': True,
        'load_calibration': False,
    })
    if research.get('decision') == 'BUY_CANDIDATE':
        return _fail('RESEARCH_MODE must not produce BUY_CANDIDATE')

    print('FINAL_CONFIDENCE_SIMULATION_INTEGRATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
