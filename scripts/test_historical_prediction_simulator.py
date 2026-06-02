#!/usr/bin/env python3
"""
Unit tests for historical prediction simulator (mock candles, no network).

Usage:
  python scripts/test_historical_prediction_simulator.py

Prints exactly HISTORICAL_PREDICTION_SIMULATOR_OK on success.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

TEST_TICKER = 'HISTSIMTEST'


def _fail(msg: str) -> int:
    print(f'HISTORICAL_PREDICTION_SIMULATOR_FAIL: {msg}', file=sys.stderr)
    return 1


def _build_candles(count: int = 80, *, breakout_at: int | None = None) -> list[dict]:
    candles: list[dict] = []
    price = 100.0
    for idx in range(count):
        day = idx + 1
        date = f'2025-01-{day:02d}' if day <= 31 else f'2025-02-{day - 31:02d}'
        high = price + 1.0
        low = price - 1.0
        close = price
        volume = 1000.0
        if breakout_at is not None and idx == breakout_at:
            close = high + 5.0
            high = close + 1.0
            volume = 3000.0
        candles.append({
            'market': 'INDIA',
            'ticker': TEST_TICKER,
            'date': date,
            'source': 'test',
            'open': price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
            'fake_prices': 0,
        })
        price = close
    return candles


def _run_tests(db_path: Path) -> str | None:
    from backend.analytics.historical_prediction_simulator import (
        ALL_STRATEGIES,
        _bearish_breakdown_20,
        _compute_rsi,
        _mean_reversion_rsi,
        _momentum_breakout_20,
        resolve_sim_outcome,
        run_historical_simulation,
    )
    from backend.storage.historical_market_store import init_db, upsert_prices

    if not init_db():
        return 'init_db failed'

    candles = _build_candles(80, breakout_at=70)
    upsert_prices(candles)

    if len(ALL_STRATEGIES) != 3:
        return 'strategy count mismatch'

    rsi = _compute_rsi([float(c['close']) for c in candles[:30]])
    if rsi is None:
        return 'RSI computation failed'

    signal = _momentum_breakout_20(candles, 70, warning_dates=set())
    if not signal or signal.get('direction') != 'BULLISH':
        return 'momentum_breakout_20 failed to fire on synthetic breakout'

    pred = {
        'sim_prediction_id': 'hsp:test',
        'ticker': TEST_TICKER,
        'signal_date': candles[70]['date'],
        'strategy': signal['strategy'],
        'direction': signal['direction'],
        'entry_price': signal['entry_price'],
        'target_price': signal['target_price'],
        'stop_loss': signal['stop_loss'],
        'horizon': signal['horizon'],
    }
    future = candles[71:76]
    outcome = resolve_sim_outcome(pred, candles[:71] + future)
    if not outcome:
        return 'resolve_sim_outcome returned None'
    if outcome.get('evidence_json', {}).get('uses_future_data'):
        return 'lookahead flag incorrectly set'

    bearish_candles = _build_candles(80)
    base_low = min(float(c['low']) for c in bearish_candles[:60])
    break_idx = 75
    break_close = base_low - 5.0
    bearish_candles[break_idx]['close'] = break_close
    bearish_candles[break_idx]['low'] = break_close - 1.0
    bearish_candles[break_idx]['high'] = break_close + 1.0
    bearish_candles[break_idx]['open'] = break_close + 0.5
    bear_signal = _bearish_breakdown_20(bearish_candles, break_idx, warning_dates=set())
    if not bear_signal or bear_signal.get('direction') != 'BEARISH':
        return 'bearish_breakdown_20 failed'

    oversold = _build_candles(80)
    for idx in range(60, 70):
        oversold[idx]['close'] = oversold[idx - 1]['close'] - 2.0
        oversold[idx]['low'] = oversold[idx]['close'] - 0.5
        oversold[idx]['high'] = oversold[idx]['close'] + 0.5
    oversold[70]['close'] = oversold[69]['close'] + 0.5
    oversold[70]['high'] = oversold[70]['close'] + 0.5
    oversold[70]['low'] = oversold[70]['close'] - 0.5
    rsi_signal = _mean_reversion_rsi(oversold, 70, warning_dates=set())
    if not rsi_signal:
        return 'mean_reversion_rsi failed on synthetic oversold'

    summary = run_historical_simulation(
        market='INDIA',
        from_date=candles[65]['date'],
        to_date=candles[-1]['date'],
        strategies=['momentum_breakout_20'],
        limit_tickers=1,
        max_signals=5,
        dry_run=True,
        write=False,
    )
    if summary.get('fake_predictions', 0) != 0:
        return 'fake_predictions should be 0'

    return None


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / 'historical_market_memory.db'
        with patch('backend.storage.historical_market_store.get_historical_db_path', return_value=db_path):
            with patch('backend.storage.historical_market_store.DATA_DIR', Path(tmp)):
                err = _run_tests(db_path)
                if err:
                    return _fail(err)

    print('HISTORICAL_PREDICTION_SIMULATOR_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
