#!/usr/bin/env python3
"""
Test external evidence integration in final confidence fusion.

Usage:
  python scripts/test_external_evidence_final_confidence.py

Prints exactly EXTERNAL_EVIDENCE_FINAL_CONFIDENCE_OK on success.
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
    print(f'EXTERNAL_EVIDENCE_FINAL_CONFIDENCE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.external_evidence_adapter import EXTERNAL_EVIDENCE_CAP
    from backend.analytics.final_confidence_fusion import (
        ADJUSTMENT_CAPS,
        score_candidate,
    )

    if ADJUSTMENT_CAPS.get('I_external_evidence') != EXTERNAL_EVIDENCE_CAP:
        return _fail('I_external_evidence cap mismatch')

    scored = score_candidate({
        'ticker': 'RELIANCE',
        'prediction_id': 'mock:ext_reliance',
        'direction': 'BUY',
        'signal_stack': {'entry_price': 100.0, 'target_price': 120.0, 'stop_loss': 90.0},
    }, context={
        'latest_prices': {'RELIANCE': 100.0},
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
        'simulation_fn': lambda _c: {'ok': True, 'confidence_adjustment': 0, 'warnings': [], 'reasons': []},
        'router_fn': lambda: {'active_mode': 'RESEARCH_MODE', 'warnings': []},
        'freshness_fn': lambda: {'safe_to_use': True, 'warnings': []},
        'load_calibration': False,
    })

    if 'external_evidence' not in scored:
        return _fail('score_candidate missing external_evidence')
    if 'external_evidence_adjustment' not in scored:
        return _fail('score_candidate missing external_evidence_adjustment')

    ext_adj = int(scored.get('external_evidence_adjustment') or 0)
    if abs(ext_adj) > EXTERNAL_EVIDENCE_CAP:
        return _fail(f'external adjustment {ext_adj} exceeds cap')

    breakdown = scored.get('score_breakdown') or []
    if not any(item.get('component') == 'external_evidence' for item in breakdown):
        return _fail('score_breakdown missing external_evidence component')

    cap_test = score_candidate({
        'ticker': 'MCX',
        'prediction_id': 'mock:ext_mcx_cap',
        'direction': 'BEARISH',
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
        'simulation_fn': lambda _c: {'ok': True, 'confidence_adjustment': 0, 'warnings': [], 'reasons': []},
        'external_evidence_fn': lambda _c, pre_decision=None: {
            'ok': True,
            'confidence_adjustment': 99,
            'warnings': [],
            'reasons': ['cap test'],
            'external_evidence': {'ok': True, 'items': [], 'counts': {}},
        },
        'router_fn': lambda: {'active_mode': 'RESEARCH_MODE', 'warnings': []},
        'freshness_fn': lambda: {'safe_to_use': True, 'warnings': []},
        'load_calibration': False,
    })
    if abs(int(cap_test.get('external_evidence_adjustment') or 0)) > EXTERNAL_EVIDENCE_CAP:
        return _fail('external evidence cap not enforced in fusion')

    research = score_candidate({
        'ticker': 'EXTRES',
        'prediction_id': 'mock:ext_res',
        'direction': 'BUY',
        'confidence_label': 'HIGH',
        'signal_stack': {'entry_price': 100.0, 'target_price': 120.0, 'stop_loss': 90.0},
    }, context={
        'latest_prices': {'EXTRES': 100.0},
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
        'simulation_fn': lambda _c: {'ok': True, 'confidence_adjustment': 0, 'warnings': [], 'reasons': []},
        'external_evidence_fn': lambda _c, pre_decision=None: {
            'ok': True,
            'confidence_adjustment': 3,
            'warnings': [],
            'reasons': ['positive external'],
            'external_evidence': {'ok': True, 'items': [], 'counts': {'positive': 1}},
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
        return _fail('RESEARCH_MODE must not produce BUY_CANDIDATE with external evidence')

    from backend.collectors.external_evidence_classifier import classify_external_item, load_universe
    from backend.analytics.external_evidence_adapter import get_ticker_external_evidence

    universe = load_universe()

    dell = classify_external_item({
        'title': 'Dell shares soar more than 30% on strong earnings',
        'description': (
            "Dell's stock soared, surpassing the company's historical reliance on PC sales."
        ),
        'source': 'Economic Times',
    }, universe)
    if dell.get('classification') == 'stock_news_evidence' and dell.get('ticker') == 'RELIANCE':
        return _fail('Dell headline must not attach to RELIANCE')

    rel_headline = classify_external_item({
        'title': 'Supreme Court provides relief to Reliance in 2007 securities market fraud case',
        'description': 'Reliance Industries Ltd received relief',
        'source': 'Economic Times',
    }, universe)
    if rel_headline.get('ticker') != 'RELIANCE':
        return _fail('Reliance headline must attach to RELIANCE')

    mcx_headline = classify_external_item({
        'title': 'MCX shares slide 3% on weak volumes',
        'description': 'Multi Commodity Exchange stock declined',
        'source': 'Moneycontrol',
    }, universe)
    if mcx_headline.get('ticker') != 'MCX':
        return _fail('MCX headline must attach only to MCX')

    macro_mcx = classify_external_item({
        'title': 'Oil prices slip as U.S.-Iran deal awaited',
        'description': 'Brent crude declined',
        'source': 'Investing.com',
    }, universe)
    if macro_mcx.get('ticker') == 'MCX':
        return _fail('fuzzy false positive: macro headline tagged MCX')

    rel_items = get_ticker_external_evidence('RELIANCE').get('items') or []
    for item in rel_items:
        title = str(item.get('title') or '')
        if 'dell' in title.lower():
            return _fail('adapter still attaches Dell to RELIANCE')

    print('EXTERNAL_EVIDENCE_FINAL_CONFIDENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
