#!/usr/bin/env python3
"""
Smoke test historical market memory store and replay logic.

Usage:
  python scripts/test_historical_market_memory.py

Prints exactly HISTORICAL_MARKET_MEMORY_TEST_OK on success; exits 1 on failure.
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

TEST_TICKER = '__TEST_HIST_REPLAY__'


def _fail(msg: str) -> int:
    print(f'HISTORICAL_MARKET_MEMORY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _cleanup() -> None:
    from backend.storage.historical_market_store import get_connection

    conn = get_connection()
    try:
        conn.execute('DELETE FROM historical_prices WHERE ticker = ?', (TEST_TICKER,))
        conn.execute('DELETE FROM historical_outcome_replay WHERE ticker = ?', (TEST_TICKER,))
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    from backend.analytics.historical_learning_engine import get_historical_learning_summary
    from backend.storage.historical_market_store import get_prices, init_db, upsert_prices
    from backend.storage.historical_outcome_replay import (
        AMBIGUOUS_RESOLVED,
        resolve_replay_from_candles,
    )

    if not init_db():
        return _fail('init_db returned False')

    _cleanup()

    candles = [
        {
            'date': '2026-05-01',
            'open': 100.0,
            'high': 101.0,
            'low': 99.0,
            'close': 100.5,
            'volume': 1000.0,
            'source': 'test',
        },
        {
            'date': '2026-05-02',
            'open': 100.5,
            'high': 106.0,
            'low': 100.0,
            'close': 105.5,
            'volume': 1200.0,
            'source': 'test',
        },
        {
            'date': '2026-05-03',
            'open': 105.0,
            'high': 106.0,
            'low': 97.0,
            'close': 98.0,
            'volume': 1500.0,
            'source': 'test',
        },
    ]

    upsert_prices([
        {
            'market': 'INDIA',
            'ticker': TEST_TICKER,
            'date': candle['date'],
            'source': candle['source'],
            'open': candle['open'],
            'high': candle['high'],
            'low': candle['low'],
            'close': candle['close'],
            'volume': candle['volume'],
            'fake_prices': 0,
        }
        for candle in candles
    ])

    loaded = get_prices(ticker=TEST_TICKER, market='INDIA')
    if len(loaded) != 3:
        return _fail(f'expected 3 price rows, got {len(loaded)}')

    bullish_win = resolve_replay_from_candles({
        'prediction_id': 'mm:test_hist_win',
        'ticker': TEST_TICKER,
        'timestamp': '2026-05-01T00:00:00+00:00',
        'direction': 'BULLISH',
        'raw_payload': {
            'entry_price': 100.0,
            'target_price': 105.0,
            'stop_loss': 98.0,
        },
    }, candles, market='INDIA')
    if not bullish_win or bullish_win.get('resolved_as') != 'WIN':
        return _fail(f'expected bullish WIN, got {bullish_win}')

    bearish_loss = resolve_replay_from_candles({
        'prediction_id': 'mm:test_hist_loss',
        'ticker': TEST_TICKER,
        'timestamp': '2026-05-01T00:00:00+00:00',
        'direction': 'BEARISH',
        'raw_payload': {
            'entry_price': 100.0,
            'target_price': 95.0,
            'stop_loss': 105.0,
        },
    }, candles, market='INDIA')
    if not bearish_loss or bearish_loss.get('resolved_as') != 'LOSS':
        return _fail(f'expected bearish LOSS, got {bearish_loss}')

    ambiguous = resolve_replay_from_candles({
        'prediction_id': 'mm:test_hist_ambiguous',
        'ticker': TEST_TICKER,
        'timestamp': '2026-05-03T00:00:00+00:00',
        'direction': 'BULLISH',
        'raw_payload': {
            'entry_price': 100.0,
            'target_price': 105.5,
            'stop_loss': 98.0,
        },
    }, candles, market='INDIA')
    if not ambiguous or ambiguous.get('resolved_as') != AMBIGUOUS_RESOLVED:
        return _fail(f'expected AMBIGUOUS_DAILY_CANDLE, got {ambiguous}')

    summary = get_historical_learning_summary(limit_prices=5)
    if not summary.get('ok'):
        return _fail('get_historical_learning_summary not ok')

    _cleanup()
    print('HISTORICAL_MARKET_MEMORY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
