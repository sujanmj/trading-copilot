"""
Replay canonical prediction outcomes using historical OHLCV prices.

Reads predictions from canonical_market_memory.db (read-only).
Writes replays only to historical_market_memory.db.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.storage.historical_market_store import (
    get_excluded_simulation_dates,
    get_prices,
    get_stats,
    get_warning_simulation_dates,
    init_db,
    insert_replay,
    rebuild_source_performance,
)
from backend.storage.market_memory_db import get_connection as get_canonical_connection
from backend.storage.market_memory_db import init_market_memory_db
from backend.storage.market_memory_outcomes import extract_prediction_price_context

HISTORICAL_HOLDING_PERIOD = 'historical_replay'
REPLAY_SOURCE = 'historical_price_replay'
AMBIGUOUS_RESOLVED = 'AMBIGUOUS_DAILY_CANDLE'


def _log(message: str) -> None:
    print(f'[HISTORICAL_REPLAY] {message}')


def _log_error(message: str) -> None:
    print(f'[HISTORICAL_REPLAY] {message}', file=sys.stderr)


def _parse_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == '-' and text[7] == '-':
        return text[:10]
    return None


def _infer_market(ticker: str) -> str:
    token = str(ticker or '').strip().upper()
    if token.startswith('^') or token.endswith('.NS') or token.endswith('.BO'):
        return 'INDIA'
    if '.' in token and not token.endswith('.NS'):
        return 'USA'
    return 'INDIA'


def _dedupe_prices_by_date(rows: list[dict]) -> list[dict]:
    """Prefer first source per date (already ordered by source ASC)."""
    seen: set[str] = set()
    output: list[dict] = []
    for row in rows:
        date = row.get('date')
        if not date or date in seen:
            continue
        seen.add(date)
        output.append(row)
    return output


def _load_replay_candles(
    *,
    market: str,
    ticker: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> tuple[list[dict], set[str], set[str]]:
    """Load candles for replay, excluding quarantined simulation dates."""
    rows = get_prices(
        market=market,
        ticker=ticker,
        from_date=from_date,
        to_date=to_date,
    )
    candles = _dedupe_prices_by_date(rows)
    excluded_dates = get_excluded_simulation_dates(market, ticker)
    warning_dates = get_warning_simulation_dates(market, ticker)
    if excluded_dates:
        candles = [
            candle for candle in candles
            if candle.get('date') not in excluded_dates
        ]
    return candles, excluded_dates, warning_dates


def _apply_anomaly_warnings(replay_payload: dict, warning_dates: set[str]) -> dict:
    """Attach historical_anomaly_warning when replay uses warning-severity dates."""
    if not replay_payload or not warning_dates:
        return replay_payload

    used_dates: set[str] = set()
    replay_date = replay_payload.get('replay_date')
    if replay_date:
        used_dates.add(str(replay_date))

    prediction_date = replay_payload.get('prediction_date')
    if prediction_date and replay_date != prediction_date:
        used_dates.add(str(prediction_date))

    flagged = sorted(date for date in used_dates if date in warning_dates)
    if not flagged:
        return replay_payload

    raw_payload = replay_payload.get('raw_payload')
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw_payload = {'raw_payload_text': raw_payload}
    if not isinstance(raw_payload, dict):
        raw_payload = {}

    raw_payload['historical_anomaly_warning'] = {
        'dates': flagged,
        'severity': 'warning',
    }
    replay_payload['raw_payload'] = raw_payload
    return replay_payload


def _candle_hits(direction: str, candle: dict, target: float, stop: float) -> tuple[bool, bool]:
    high = float(candle['high'])
    low = float(candle['low'])
    if direction == 'BULLISH':
        return high >= target, low <= stop
    return low <= target, high >= stop


def resolve_replay_from_candles(
    prediction: dict,
    candles: list[dict],
    *,
    market: str | None = None,
) -> dict | None:
    """Resolve one replay outcome by walking daily candles."""
    prediction_id = prediction.get('prediction_id')
    if not prediction_id:
        return None

    ctx = extract_prediction_price_context(prediction)
    if not ctx:
        return None

    entry = ctx.get('entry_price')
    target = ctx.get('target_price')
    stop = ctx.get('stop_loss')
    direction = ctx.get('direction')
    if entry is None or target is None or stop is None or direction not in ('BULLISH', 'BEARISH'):
        return None

    prediction_date = _parse_date(prediction.get('timestamp'))
    if not prediction_date:
        return None

    eligible = [
        candle for candle in candles
        if candle.get('date') and candle['date'] >= prediction_date
    ]
    if not eligible:
        return None

    resolved_as = 'UNRESOLVED'
    expiry_result = 'NO_HIT_IN_RANGE'
    replay_date = None
    hit_candle: dict | None = None

    for candle in eligible:
        try:
            target_hit, stop_hit = _candle_hits(direction, candle, float(target), float(stop))
        except (TypeError, ValueError, KeyError):
            continue

        if target_hit and stop_hit:
            resolved_as = AMBIGUOUS_RESOLVED
            expiry_result = 'TARGET_AND_STOP_SAME_CANDLE'
            replay_date = candle.get('date')
            hit_candle = candle
            break
        if target_hit:
            resolved_as = 'WIN'
            expiry_result = 'TARGET_HIT_BY_HISTORICAL_CANDLE'
            replay_date = candle.get('date')
            hit_candle = candle
            break
        if stop_hit:
            resolved_as = 'LOSS'
            expiry_result = 'STOP_LOSS_HIT_BY_HISTORICAL_CANDLE'
            replay_date = candle.get('date')
            hit_candle = candle
            break

    actual_move = None
    if hit_candle and entry:
        try:
            close = float(hit_candle.get('close'))
            actual_move = ((close - float(entry)) / float(entry)) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            actual_move = None

    ticker = str(ctx.get('ticker') or prediction.get('ticker') or '').strip().upper()
    return {
        'prediction_id': prediction_id,
        'ticker': ticker,
        'market': market or _infer_market(ticker),
        'prediction_date': prediction_date,
        'direction': direction,
        'entry_price': entry,
        'target_price': target,
        'stop_loss': stop,
        'holding_period': HISTORICAL_HOLDING_PERIOD,
        'resolved_as': resolved_as,
        'expiry_result': expiry_result,
        'replay_date': replay_date,
        'candle_high': hit_candle.get('high') if hit_candle else None,
        'candle_low': hit_candle.get('low') if hit_candle else None,
        'candle_close': hit_candle.get('close') if hit_candle else None,
        'actual_move': actual_move,
        'source': prediction.get('source') or REPLAY_SOURCE,
        'raw_payload': {
            'replay_source': REPLAY_SOURCE,
            'prediction_id': prediction_id,
            'prediction_timestamp': prediction.get('timestamp'),
            'candles_considered': len(eligible),
        },
    }


def fetch_canonical_predictions(
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Read predictions from canonical DB (query-only)."""
    init_market_memory_db()
    conn = get_canonical_connection()
    try:
        conn.execute('PRAGMA query_only = ON')
        query = """
            SELECT *
            FROM predictions
            WHERE ticker IS NOT NULL
              AND TRIM(ticker) != ''
              AND ticker NOT LIKE '__TEST__%'
        """
        params: list[Any] = []
        if from_date:
            query += ' AND substr(timestamp, 1, 10) >= ?'
            params.append(from_date)
        if to_date:
            query += ' AND substr(timestamp, 1, 10) <= ?'
            params.append(to_date)
        query += ' ORDER BY timestamp ASC'
        if limit is not None and limit > 0:
            query += ' LIMIT ?'
            params.append(int(limit))
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def replay_prediction_outcomes(
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    market: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Replay canonical predictions against historical OHLCV prices."""
    init_db()
    summary: dict[str, Any] = {
        'dry_run': dry_run,
        'from_date': from_date,
        'to_date': to_date,
        'market': market,
        'limit': limit,
        'stats_before': get_stats(),
        'predictions_checked': 0,
        'resolved': 0,
        'written': 0,
        'skipped': 0,
        'errors': 0,
        'wins': 0,
        'losses': 0,
        'ambiguous': 0,
        'unresolved': 0,
        'resolved_by': {
            'TARGET_HIT_BY_HISTORICAL_CANDLE': 0,
            'STOP_LOSS_HIT_BY_HISTORICAL_CANDLE': 0,
            'TARGET_AND_STOP_SAME_CANDLE': 0,
            'NO_HIT_IN_RANGE': 0,
        },
        'skip_reasons': {
            'missing_price_context': 0,
            'missing_historical_prices': 0,
        },
        'anomaly_excluded_dates': 0,
        'anomaly_warnings': 0,
    }

    try:
        predictions = fetch_canonical_predictions(
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
        summary['predictions_checked'] = len(predictions)

        price_cache: dict[tuple[str, str], list[dict]] = {}
        anomaly_cache: dict[tuple[str, str], tuple[set[str], set[str]]] = {}

        for prediction in predictions:
            ctx = extract_prediction_price_context(prediction)
            if not ctx:
                summary['skipped'] += 1
                summary['skip_reasons']['missing_price_context'] += 1
                continue

            ticker = str(ctx['ticker']).strip().upper()
            inferred_market = market or _infer_market(ticker)
            cache_key = (inferred_market, ticker)
            if cache_key not in price_cache:
                candles, excluded_dates, warning_dates = _load_replay_candles(
                    market=inferred_market,
                    ticker=ticker,
                    from_date=from_date,
                    to_date=to_date,
                )
                price_cache[cache_key] = candles
                anomaly_cache[cache_key] = (excluded_dates, warning_dates)
                summary['anomaly_excluded_dates'] += len(excluded_dates)

            candles = price_cache[cache_key]
            excluded_dates, warning_dates = anomaly_cache[cache_key]
            if not candles:
                summary['skipped'] += 1
                summary['skip_reasons']['missing_historical_prices'] += 1
                if verbose:
                    _log(f'skip {prediction.get("prediction_id")}: no prices for {ticker}')
                continue

            replay_payload = resolve_replay_from_candles(
                prediction,
                candles,
                market=inferred_market,
            )
            if not replay_payload:
                summary['skipped'] += 1
                continue

            replay_payload = _apply_anomaly_warnings(replay_payload, warning_dates)
            if (
                isinstance(replay_payload.get('raw_payload'), dict)
                and replay_payload['raw_payload'].get('historical_anomaly_warning')
            ):
                summary['anomaly_warnings'] += 1

            summary['resolved'] += 1
            resolved_as = replay_payload.get('resolved_as')
            expiry_result = replay_payload.get('expiry_result')
            if resolved_as == 'WIN':
                summary['wins'] += 1
            elif resolved_as == 'LOSS':
                summary['losses'] += 1
            elif resolved_as == AMBIGUOUS_RESOLVED:
                summary['ambiguous'] += 1
            else:
                summary['unresolved'] += 1

            if expiry_result in summary['resolved_by']:
                summary['resolved_by'][expiry_result] += 1

            if verbose:
                _log(
                    f'replay {prediction.get("prediction_id")}: '
                    f'{resolved_as}/{expiry_result} ticker={ticker}',
                )

            if dry_run:
                continue

            replay_id = insert_replay(replay_payload)
            if replay_id:
                summary['written'] += 1
            else:
                summary['errors'] += 1

        if not dry_run and summary['written'] > 0:
            rebuild_source_performance(market=market)

        summary['stats_after'] = get_stats()
        return summary
    except Exception as exc:
        _log_error(f'replay_prediction_outcomes failed: {exc}')
        summary['errors'] += 1
        summary['stats_after'] = get_stats()
        return summary


def is_valid_ohlcv_row(row: dict) -> bool:
    """Reject NaN/invalid OHLCV values."""
    for field in ('open', 'high', 'low', 'close', 'volume'):
        val = row.get(field)
        if val is None:
            return False
        try:
            num = float(val)
        except (TypeError, ValueError):
            return False
        if math.isnan(num) or math.isinf(num):
            return False
    try:
        high = float(row['high'])
        low = float(row['low'])
        if low > high:
            return False
    except (TypeError, ValueError, KeyError):
        return False
    return True
