#!/usr/bin/env python3
"""
Unit tests for broker DB write gate (Stage 39E).

Prints BROKER_WRITE_GATE_TEST_OK on success.
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
    print(f'BROKER_WRITE_GATE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors.broker_db_write_gate import (
        build_broker_write_review,
        evaluate_broker_write_eligibility,
    )

    top_pick = evaluate_broker_write_eligibility({
        'ticker': 'ICICIBANK',
        'title': 'Nomura top pick: ICICI Bank with target price Rs 1,500, recommends Buy',
        'source': 'Economic Times',
        'direction': 'BULLISH',
        'direction_confidence': 'explicit',
        'classification': 'broker_prediction_candidate',
        'classification_reason': 'explicit_recommendation_with_ticker',
    })
    if top_pick['eligibility'] != 'write_safe':
        return _fail(f'top pick broker rec: {top_pick}')

    manual = evaluate_broker_write_eligibility({
        'ticker': 'RELIANCE',
        'title': 'Manual inbox: Reliance accumulate on dips',
        'source': 'Manual Inbox',
        'direction': 'BULLISH',
        'direction_confidence': 'explicit',
        'classification': 'broker_prediction_candidate',
        'raw_payload': {'collector_source': 'manual'},
    })
    if manual['eligibility'] != 'write_safe':
        return _fail(f'manual inbox: {manual}')

    block_deal = evaluate_broker_write_eligibility({
        'ticker': 'POLICYBZR',
        'title': 'PB Fintech sees Rs 665 crore block deal; Goldman among other buyers',
        'source': 'Moneycontrol',
        'direction': 'BULLISH',
        'classification': 'broker_prediction_candidate',
    })
    if block_deal['eligibility'] == 'write_safe':
        return _fail(f'block deal must not be write_safe: {block_deal}')

    credit = evaluate_broker_write_eligibility({
        'ticker': 'RELIANCE',
        'title': "Moody's upgrades Reliance Industries credit rating outlook to positive",
        'source': 'LiveMint',
        'direction': 'WATCH',
        'classification': 'broker_prediction_candidate',
    })
    if credit['eligibility'] == 'write_safe':
        return _fail(f'credit rating must not be write_safe: {credit}')

    question = evaluate_broker_write_eligibility({
        'ticker': 'TCS',
        'title': 'Should you buy, sell or hold TCS after Q4 results?',
        'source': 'ET Markets',
        'direction': 'WATCH',
        'classification': 'broker_prediction_candidate',
    })
    if question['eligibility'] == 'write_safe':
        return _fail(f'question headline must not be write_safe: {question}')

    rally = evaluate_broker_write_eligibility({
        'ticker': 'SUZLON',
        'title': 'Suzlon shares rally 8% on strong order book update',
        'source': 'Moneycontrol',
        'direction': 'BULLISH',
        'classification': 'stock_news_evidence',
    })
    if rally['eligibility'] == 'write_safe':
        return _fail(f'price rally must not be write_safe: {rally}')

    no_ticker = evaluate_broker_write_eligibility({
        'title': 'Sensex ends flat; Nifty holds 22,500',
        'source': 'Business Standard',
        'direction': 'NEUTRAL',
        'classification': 'market_context',
    })
    if no_ticker['eligibility'] != 'reject':
        return _fail(f'no ticker must reject: {no_ticker}')

    watch_only = evaluate_broker_write_eligibility({
        'ticker': 'RELIANCE',
        'title': 'Stocks to watch today: Reliance, TCS in focus',
        'source': 'Moneycontrol',
        'direction': 'WATCH',
        'direction_confidence': 'watch_only',
        'classification': 'broker_prediction_candidate',
    })
    if watch_only['eligibility'] == 'write_safe':
        return _fail(f'watch list must not be write_safe: {watch_only}')

    review = build_broker_write_review([
        {
            'ticker': 'ICICIBANK',
            'title': 'Nomura top pick: ICICI Bank recommends Buy',
            'source': 'Economic Times',
            'direction': 'BULLISH',
            'direction_confidence': 'explicit',
            'classification': 'broker_prediction_candidate',
        },
        {
            'ticker': 'POLICYBZR',
            'title': 'PB Fintech block deal; Goldman among buyers',
            'source': 'Moneycontrol',
            'direction': 'BULLISH',
            'classification': 'broker_prediction_candidate',
        },
        {
            'title': 'Sensex ends flat',
            'source': 'Business Standard',
            'classification': 'market_context',
        },
    ])
    summary = review.get('summary') or {}
    if summary.get('write_safe', 0) < 1:
        return _fail(f'build review write_safe count: {summary}')
    if summary.get('rejected', 0) < 1:
        return _fail(f'build review rejected count: {summary}')

    print('BROKER_WRITE_GATE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
