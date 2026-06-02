#!/usr/bin/env python3
"""
Smoke test for market memory shadow learning advisor.

Usage:
  python scripts/test_market_memory_advisor.py

Prints exactly MARKET_MEMORY_ADVISOR_OK on success; exits 1 on failure.
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

TEST_TICKER_BOOST = '__TEST_ADVISOR_BOOST__'
TEST_TICKER_AVOID = '__TEST_ADVISOR_AVOID__'
TEST_TICKER_LOW = '__TEST_ADVISOR_LOW__'
TEST_HOLDING = 'test_advisor'
TEST_SIGNAL = 'advisor_test_signal'


def _fail(msg: str) -> int:
    print(f'MARKET_MEMORY_ADVISOR_FAIL: {msg}', file=sys.stderr)
    return 1


def _cleanup(conn) -> None:
    tickers = (TEST_TICKER_BOOST, TEST_TICKER_AVOID, TEST_TICKER_LOW)
    for ticker in tickers:
        conn.execute(
            'DELETE FROM outcomes WHERE prediction_id IN (SELECT prediction_id FROM predictions WHERE ticker = ?)',
            (ticker,),
        )
        conn.execute('DELETE FROM predictions WHERE ticker = ?', (ticker,))
    conn.commit()


def _insert_case(
    *,
    idx: int,
    ticker: str,
    resolved_as: str,
    actual_move: float,
) -> str:
    from backend.storage.market_memory_db import upsert_outcome, upsert_prediction

    prediction_id = upsert_prediction({
        'prediction_id': f'mm:test_advisor_{ticker}_{idx}',
        'ticker': ticker,
        'timestamp': f'2026-05-29T13:00:{idx:02d}+00:00',
        'source': 'advisor_test',
        'direction': 'BUY',
        'confidence_label': 'HIGH',
        'signal_stack': {
            'signal_type': TEST_SIGNAL,
            'prediction_horizon': 'intraday',
            'broker_consensus': {'agreement_direction': 'BULLISH'},
        },
    })
    if not prediction_id:
        raise RuntimeError(f'upsert_prediction failed for {ticker} idx={idx}')
    if not upsert_outcome({
        'prediction_id': prediction_id,
        'holding_period': TEST_HOLDING,
        'resolved_as': resolved_as,
        'actual_move': actual_move,
    }):
        raise RuntimeError(f'upsert_outcome failed for {ticker} idx={idx}')
    return prediction_id


def main() -> int:
    from backend.analytics.market_memory_advisor import advise_prediction, advise_ticker
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    conn = get_connection()
    try:
        _cleanup(conn)
    finally:
        conn.close()

    try:
        for idx in range(6):
            _insert_case(idx=idx, ticker=TEST_TICKER_BOOST, resolved_as='WIN', actual_move=1.0)
        for idx in range(6):
            _insert_case(idx=idx, ticker=TEST_TICKER_AVOID, resolved_as='LOSS', actual_move=-1.0)
        _insert_case(idx=0, ticker=TEST_TICKER_LOW, resolved_as='LOSS', actual_move=-0.5)

        boost_advice = advise_ticker(TEST_TICKER_BOOST)
        if boost_advice.get('overall_advice') != 'boost':
            return _fail(
                f'expected boost for 6W/0L ticker, got {boost_advice.get("overall_advice")}'
            )
        boost_component = (boost_advice.get('components') or {}).get('ticker') or {}
        if boost_component.get('sample_size', 0) < 5:
            return _fail('boost ticker sample_size below gate')

        avoid_advice = advise_ticker(TEST_TICKER_AVOID)
        if avoid_advice.get('overall_advice') != 'avoid_candidate':
            return _fail(
                f'expected avoid_candidate for 0W/6L ticker, got {avoid_advice.get("overall_advice")}'
            )

        low_advice = advise_ticker(TEST_TICKER_LOW)
        if low_advice.get('overall_advice') != 'neutral':
            return _fail(
                f'expected neutral for 1L only ticker, got {low_advice.get("overall_advice")}'
            )
        low_warnings = low_advice.get('warnings') or []
        if 'low_sample_size' not in low_warnings:
            return _fail('expected low_sample_size warning for 1L only ticker')

        candidate_advice = advise_prediction({
            'ticker': TEST_TICKER_BOOST,
            'signal_type': TEST_SIGNAL,
            'confidence_label': 'HIGH',
            'prediction_horizon': 'intraday',
            'broker_consensus': {'agreement_direction': 'BULLISH'},
        })
        if candidate_advice.get('shadow_mode') is not True:
            return _fail('shadow_mode must be true')
        if not candidate_advice.get('components'):
            return _fail('advise_prediction missing components')

        for key in ('overall_advice', 'learning_score', 'sample_size', 'warnings', 'reasons', 'components'):
            if key not in candidate_advice:
                return _fail(f'missing output key: {key}')

    finally:
        conn = get_connection()
        try:
            _cleanup(conn)
        finally:
            conn.close()

    print('MARKET_MEMORY_ADVISOR_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
