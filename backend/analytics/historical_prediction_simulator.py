"""
Historical prediction simulation engine — backtest samples from OHLCV only.

Generates simulated prediction setups from historical candles and resolves outcomes
using candles AFTER the signal date only. Writes ONLY to historical_market_memory.db.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.storage.historical_market_store import (
    compute_simulation_params_hash,
    delete_simulation_by_params_hash,
    find_run_by_params_hash,
    get_excluded_simulation_dates,
    get_prices,
    get_simulation_stats,
    get_simulation_tickers,
    get_stats,
    get_strategy_performance,
    get_warning_simulation_dates,
    init_db,
    insert_run,
    list_runs,
    make_sim_outcome_id,
    make_sim_prediction_id,
    make_simulation_run_id,
    make_simulation_run_id_from_params_hash,
    rebuild_strategy_performance,
    upsert_sim_outcomes,
    upsert_sim_predictions,
)
from backend.storage.historical_outcome_replay import (
    AMBIGUOUS_RESOLVED,
    _candle_hits,
    _dedupe_prices_by_date,
)

ALL_STRATEGIES = (
    'momentum_breakout_20',
    'mean_reversion_rsi',
    'bearish_breakdown_20',
)

MIN_HISTORY_CANDLES = 60
LOOKBACK_20 = 20
RSI_PERIOD = 14
HORIZON_BARS = {'swing_5d': 5}
EXPIRED_FLAT_THRESHOLD = 0.25
SIM_SOURCE = 'historical_prediction_simulation'


def _log(message: str) -> None:
    print(f'[HIST_SIM] {message}')


def _log_error(message: str) -> None:
    print(f'[HIST_SIM] {message}', file=sys.stderr)


def _parse_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4] == '-' and text[7] == '-':
        return text[:10]
    return None


def _years_to_range(years: int) -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=int(years) * 365)
    return start.isoformat(), today.isoformat()


def _compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    if len(closes) < period + 1:
        return None
    window = closes[-(period + 1):]
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, len(window)):
        delta = window[idx] - window[idx - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 0.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _is_valid_signal_candle(candle: dict) -> bool:
    if int(candle.get('fake_prices') or 0) != 0:
        return False
    for field in ('open', 'high', 'low', 'close'):
        val = candle.get(field)
        if val is None:
            return False
        try:
            num = float(val)
        except (TypeError, ValueError):
            return False
        if math.isnan(num) or math.isinf(num):
            return False
    try:
        high = float(candle['high'])
        low = float(candle['low'])
        if low > high:
            return False
    except (TypeError, ValueError, KeyError):
        return False
    return True


def _volume_check(signal: dict, window: list[dict]) -> bool:
    volumes = [row.get('volume') for row in window]
    if any(v is None for v in volumes):
        return True
    try:
        avg_vol = sum(float(v) for v in volumes) / len(volumes)
        sig_vol = float(signal.get('volume'))
    except (TypeError, ValueError, ZeroDivisionError):
        return True
    if avg_vol <= 0:
        return True
    return sig_vol > (1.5 * avg_vol)


def _momentum_breakout_20(
    candles: list[dict],
    idx: int,
    *,
    warning_dates: set[str],
) -> dict | None:
    if idx < MIN_HISTORY_CANDLES:
        return None
    signal = candles[idx]
    if not _is_valid_signal_candle(signal):
        return None
    past = candles[idx - LOOKBACK_20:idx]
    if len(past) < LOOKBACK_20:
        return None
    try:
        close = float(signal['close'])
        high_20 = max(float(row['high']) for row in past)
    except (TypeError, ValueError, KeyError):
        return None
    if close <= high_20:
        return None
    if not _volume_check(signal, past):
        return None

    entry = close
    features: dict[str, Any] = {
        'strategy': 'momentum_breakout_20',
        'high_20': high_20,
        'close': close,
        'simulation': True,
        'fake_prediction': False,
    }
    if signal.get('date') in warning_dates:
        features['anomaly_warning'] = True
        features['warning_date'] = signal.get('date')

    return {
        'strategy': 'momentum_breakout_20',
        'direction': 'BULLISH',
        'entry_price': entry,
        'target_price': entry * 1.05,
        'stop_loss': entry * 0.97,
        'horizon': 'swing_5d',
        'confidence': 0.6,
        'features_json': features,
    }


def _mean_reversion_rsi(
    candles: list[dict],
    idx: int,
    *,
    warning_dates: set[str],
) -> dict | None:
    if idx < MIN_HISTORY_CANDLES:
        return None
    signal = candles[idx]
    if not _is_valid_signal_candle(signal):
        return None
    past = candles[:idx]
    closes: list[float] = []
    for row in past:
        try:
            closes.append(float(row['close']))
        except (TypeError, ValueError, KeyError):
            return None
    rsi = _compute_rsi(closes, RSI_PERIOD)
    if rsi is None or rsi >= 30:
        return None
    try:
        close = float(signal['close'])
        prev_close = float(candles[idx - 1]['close'])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    if close <= prev_close:
        return None

    entry = close
    features: dict[str, Any] = {
        'strategy': 'mean_reversion_rsi',
        'rsi_14': round(rsi, 4),
        'close': close,
        'prev_close': prev_close,
        'simulation': True,
        'fake_prediction': False,
    }
    if signal.get('date') in warning_dates:
        features['anomaly_warning'] = True
        features['warning_date'] = signal.get('date')

    return {
        'strategy': 'mean_reversion_rsi',
        'direction': 'BULLISH',
        'entry_price': entry,
        'target_price': entry * 1.04,
        'stop_loss': entry * 0.97,
        'horizon': 'swing_5d',
        'confidence': 0.55,
        'features_json': features,
    }


def _bearish_breakdown_20(
    candles: list[dict],
    idx: int,
    *,
    warning_dates: set[str],
) -> dict | None:
    if idx < MIN_HISTORY_CANDLES:
        return None
    signal = candles[idx]
    if not _is_valid_signal_candle(signal):
        return None
    past = candles[idx - LOOKBACK_20:idx]
    if len(past) < LOOKBACK_20:
        return None
    try:
        close = float(signal['close'])
        low_20 = min(float(row['low']) for row in past)
    except (TypeError, ValueError, KeyError):
        return None
    if close >= low_20:
        return None

    entry = close
    features: dict[str, Any] = {
        'strategy': 'bearish_breakdown_20',
        'low_20': low_20,
        'close': close,
        'simulation': True,
        'fake_prediction': False,
    }
    if signal.get('date') in warning_dates:
        features['anomaly_warning'] = True
        features['warning_date'] = signal.get('date')

    return {
        'strategy': 'bearish_breakdown_20',
        'direction': 'BEARISH',
        'entry_price': entry,
        'target_price': entry * 0.95,
        'stop_loss': entry * 1.03,
        'horizon': 'swing_5d',
        'confidence': 0.6,
        'features_json': features,
    }


STRATEGY_GENERATORS = {
    'momentum_breakout_20': _momentum_breakout_20,
    'mean_reversion_rsi': _mean_reversion_rsi,
    'bearish_breakdown_20': _bearish_breakdown_20,
}


def _load_ticker_candles(
    *,
    market: str,
    ticker: str,
    from_date: str | None,
    to_date: str | None,
) -> tuple[list[dict], set[str], set[str]]:
    rows = get_prices(market=market, ticker=ticker, from_date=from_date, to_date=to_date)
    candles = _dedupe_prices_by_date(rows)
    excluded = get_excluded_simulation_dates(market, ticker)
    warning = get_warning_simulation_dates(market, ticker)
    if excluded:
        candles = [c for c in candles if c.get('date') not in excluded]
    return candles, excluded, warning


def _resolve_expired_result(direction: str, close_move_pct: float) -> str:
    if abs(close_move_pct) <= EXPIRED_FLAT_THRESHOLD:
        return 'EXPIRED_FLAT'
    if direction == 'BULLISH':
        if close_move_pct > 0:
            return 'WIN'
        if close_move_pct < 0:
            return 'LOSS'
        return 'NEUTRAL'
    if direction == 'BEARISH':
        if close_move_pct > 0:
            return 'WIN'
        if close_move_pct < 0:
            return 'LOSS'
        return 'NEUTRAL'
    return 'NEUTRAL'


def resolve_sim_outcome(
    prediction: dict,
    candles: list[dict],
) -> dict | None:
    """Resolve one simulated outcome using candles strictly AFTER signal_date."""
    signal_date = _parse_date(prediction.get('signal_date'))
    direction = str(prediction.get('direction') or '').upper()
    entry = prediction.get('entry_price')
    target = prediction.get('target_price')
    stop = prediction.get('stop_loss')
    horizon = prediction.get('horizon') or 'swing_5d'
    if not signal_date or direction not in ('BULLISH', 'BEARISH'):
        return None
    try:
        entry_f = float(entry)
        target_f = float(target)
        stop_f = float(stop)
    except (TypeError, ValueError):
        return None

    eligible = [
        candle for candle in candles
        if candle.get('date') and candle['date'] > signal_date
    ]
    max_bars = HORIZON_BARS.get(horizon, 5)
    horizon_candles = eligible[:max_bars]
    if not horizon_candles:
        return None

    result = 'UNRESOLVED'
    expiry_result = 'NO_HIT_IN_RANGE'
    bars_held = 0
    hit_candle: dict | None = None

    for candle in horizon_candles:
        if not _is_valid_signal_candle(candle):
            continue
        bars_held += 1
        try:
            target_hit, stop_hit = _candle_hits(direction, candle, target_f, stop_f)
        except (TypeError, ValueError, KeyError):
            continue
        if target_hit and stop_hit:
            result = AMBIGUOUS_RESOLVED
            expiry_result = 'TARGET_AND_STOP_SAME_CANDLE'
            hit_candle = candle
            break
        if target_hit:
            result = 'WIN'
            expiry_result = 'TARGET_HIT'
            hit_candle = candle
            break
        if stop_hit:
            result = 'LOSS'
            expiry_result = 'STOP_LOSS_HIT'
            hit_candle = candle
            break

    highs: list[float] = []
    lows: list[float] = []
    for candle in horizon_candles[:bars_held or len(horizon_candles)]:
        try:
            highs.append(float(candle['high']))
            lows.append(float(candle['low']))
        except (TypeError, ValueError, KeyError):
            continue

    if direction == 'BULLISH':
        max_gain_pct = (
            ((max(highs) - entry_f) / entry_f) * 100.0 if highs else None
        )
        max_loss_pct = (
            ((min(lows) - entry_f) / entry_f) * 100.0 if lows else None
        )
    else:
        max_gain_pct = (
            ((entry_f - min(lows)) / entry_f) * 100.0 if lows else None
        )
        max_loss_pct = (
            ((entry_f - max(highs)) / entry_f) * 100.0 if highs else None
        )

    expiry_candle = hit_candle or horizon_candles[min(bars_held, len(horizon_candles)) - 1]
    close_move_pct = None
    try:
        close = float(expiry_candle.get('close'))
        if direction == 'BULLISH':
            close_move_pct = ((close - entry_f) / entry_f) * 100.0
        else:
            close_move_pct = ((entry_f - close) / entry_f) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        close_move_pct = None

    if result == 'UNRESOLVED' and close_move_pct is not None:
        result = _resolve_expired_result(direction, close_move_pct)
        expiry_result = 'EXPIRED'

    return {
        'sim_prediction_id': prediction.get('sim_prediction_id'),
        'ticker': prediction.get('ticker'),
        'signal_date': signal_date,
        'strategy': prediction.get('strategy'),
        'result': result,
        'expiry_result': expiry_result,
        'max_gain_pct': max_gain_pct,
        'max_loss_pct': max_loss_pct,
        'close_move_pct': close_move_pct,
        'bars_held': bars_held or len(horizon_candles),
        'evidence_json': {
            'simulation': True,
            'fake_prediction': False,
            'signal_date': signal_date,
            'direction': direction,
            'horizon': horizon,
            'horizon_bars': max_bars,
            'resolved_on': hit_candle.get('date') if hit_candle else expiry_candle.get('date'),
            'uses_future_data': False,
        },
    }


def _load_tickers(
    *,
    market: str,
    limit_tickers: int | None,
) -> list[str]:
    return get_simulation_tickers(market=market, limit_tickers=limit_tickers)


def _generate_signals_for_ticker(
    *,
    run_id: str,
    market: str,
    ticker: str,
    from_date: str,
    to_date: str,
    strategies: list[str],
    max_signals: int,
    excluded_dates: set[str],
    warning_dates: set[str],
) -> tuple[list[dict], list[dict]]:
    candles, _, _ = _load_ticker_candles(
        market=market,
        ticker=ticker,
        from_date=None,
        to_date=to_date,
    )
    if len(candles) < MIN_HISTORY_CANDLES + 1:
        return [], candles

    predictions: list[dict] = []
    per_strategy_count: dict[str, int] = {name: 0 for name in strategies}

    for idx, candle in enumerate(candles):
        signal_date = candle.get('date')
        if not signal_date or signal_date < from_date or signal_date > to_date:
            continue
        if signal_date in excluded_dates:
            continue

        for strategy in strategies:
            if per_strategy_count[strategy] >= max_signals:
                continue
            generator = STRATEGY_GENERATORS.get(strategy)
            if not generator:
                continue
            signal = generator(candles, idx, warning_dates=warning_dates)
            if not signal:
                continue
            sim_prediction_id = make_sim_prediction_id(
                run_id, market, ticker, signal_date, strategy,
            )
            predictions.append({
                'sim_prediction_id': sim_prediction_id,
                'run_id': run_id,
                'market': market,
                'ticker': ticker,
                'signal_date': signal_date,
                **signal,
            })
            per_strategy_count[strategy] += 1

    return predictions, candles


def run_historical_simulation(
    *,
    market: str = 'INDIA',
    from_date: str | None = None,
    to_date: str | None = None,
    years: int | None = None,
    strategies: list[str] | None = None,
    limit_tickers: int | None = None,
    max_signals: int = 200,
    dry_run: bool = True,
    write: bool = False,
    verbose: bool = False,
    replace_existing: bool = False,
    allow_duplicate: bool = False,
    run_label: str | None = None,
    anomaly_exclusion_mode: str = 'exclude_from_simulation',
) -> dict[str, Any]:
    """Run historical prediction simulation over OHLCV data."""
    init_db()
    market = str(market or 'INDIA').strip().upper()
    selected = strategies or list(ALL_STRATEGIES)
    selected = [s for s in selected if s in STRATEGY_GENERATORS]
    if not selected:
        selected = list(ALL_STRATEGIES)

    if not from_date or not to_date:
        from_date, to_date = _years_to_range(years or 1)

    strategy_set = ','.join(selected)
    tickers = _load_tickers(market=market, limit_tickers=limit_tickers)
    params_hash = compute_simulation_params_hash(
        market=market,
        from_date=from_date,
        to_date=to_date,
        years=years,
        strategy_set=strategy_set,
        tickers=tickers,
        limit_tickers=limit_tickers,
        max_signals_per_ticker_strategy=max_signals,
        anomaly_exclusion_mode=anomaly_exclusion_mode,
    )

    if allow_duplicate:
        run_id = make_simulation_run_id(market, from_date, to_date, strategy_set)
    else:
        run_id = make_simulation_run_id_from_params_hash(params_hash)

    summary: dict[str, Any] = {
        'run_id': run_id,
        'params_hash': params_hash,
        'market': market,
        'from_date': from_date,
        'to_date': to_date,
        'strategy_set': strategy_set,
        'strategies': selected,
        'dry_run': dry_run,
        'write': write,
        'replace_existing': replace_existing,
        'allow_duplicate': allow_duplicate,
        'run_label': run_label,
        'tickers': 0,
        'signals_generated': 0,
        'resolved': 0,
        'wins': 0,
        'losses': 0,
        'ambiguous': 0,
        'written': 0,
        'duplicate_existing_run': None,
        'fake_predictions': 0,
        'stats_before': get_stats(),
        'predictions': [],
        'outcomes': [],
    }

    summary['tickers'] = len(tickers)

    all_predictions: list[dict] = []
    all_outcomes: list[dict] = []

    for ticker in tickers:
        excluded = get_excluded_simulation_dates(market, ticker)
        warning = get_warning_simulation_dates(market, ticker)
        predictions, candles = _generate_signals_for_ticker(
            run_id=run_id,
            market=market,
            ticker=ticker,
            from_date=from_date,
            to_date=to_date,
            strategies=selected,
            max_signals=max_signals,
            excluded_dates=excluded,
            warning_dates=warning,
        )
        if verbose and predictions:
            _log(f'{ticker}: generated {len(predictions)} signals')

        for prediction in predictions:
            outcome = resolve_sim_outcome(prediction, candles)
            if not outcome:
                continue
            outcome['sim_outcome_id'] = make_sim_outcome_id(prediction['sim_prediction_id'])
            all_predictions.append(prediction)
            all_outcomes.append(outcome)

    summary['signals_generated'] = len(all_predictions)
    summary['resolved'] = len(all_outcomes)
    summary['predictions'] = all_predictions
    summary['outcomes'] = all_outcomes

    for outcome in all_outcomes:
        token = str(outcome.get('result') or '').upper()
        if token == 'WIN' or token.startswith('WIN'):
            summary['wins'] += 1
        elif token == 'LOSS' or token.startswith('LOSS'):
            summary['losses'] += 1
        elif token == AMBIGUOUS_RESOLVED:
            summary['ambiguous'] += 1

    if dry_run or not write:
        summary['stats_after'] = get_stats()
        return summary

    existing = None if allow_duplicate else find_run_by_params_hash(params_hash)
    if replace_existing and existing:
        delete_simulation_by_params_hash(params_hash)
        existing = None

    if existing and not allow_duplicate:
        summary['duplicate_existing_run'] = existing.get('run_id')
        summary['written'] = 0
        summary['stats_after'] = get_stats()
        return summary

    params_json: dict[str, Any] = {
        'strategies': selected,
        'tickers': tickers,
        'limit_tickers': limit_tickers,
        'max_signals_per_ticker_strategy': max_signals,
        'dry_run': dry_run,
        'simulation': True,
        'params_hash': params_hash,
        'anomaly_exclusion_mode': anomaly_exclusion_mode,
    }
    if years is not None:
        params_json['years'] = years
    if run_label:
        params_json['run_label'] = run_label

    run_written = insert_run({
        'run_id': run_id,
        'strategy_set': strategy_set,
        'market': market,
        'from_date': from_date,
        'to_date': to_date,
        'tickers': summary['tickers'],
        'generated_predictions': summary['signals_generated'],
        'resolved_predictions': summary['resolved'],
        'wins': summary['wins'],
        'losses': summary['losses'],
        'ambiguous': summary['ambiguous'],
        'params_hash': params_hash,
        'params_json': params_json,
    })
    preds_written = upsert_sim_predictions(all_predictions)
    outcomes_written = upsert_sim_outcomes(all_outcomes)
    rebuild_strategy_performance(market=market)
    summary['written'] = int(bool(run_written)) + preds_written + outcomes_written
    summary['stats_after'] = get_stats()
    return summary


def get_simulation_dashboard(*, market: str | None = None) -> dict[str, Any]:
    """Return simulation stats for API/dashboard consumption."""
    init_db()
    stats = get_simulation_stats()
    runs = list_runs(market=market, limit=10)
    strategies = get_strategy_performance(market=market)
    return {
        'ok': True,
        'simulation': {
            'stats': stats,
            'runs': runs,
            'strategy_performance': strategies,
            'disclaimer': (
                'Simulated predictions are backtest samples, not live predictions.'
            ),
        },
    }
