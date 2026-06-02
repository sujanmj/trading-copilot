"""
Resolve prediction outcomes into canonical_market_memory.db.

Safe when predictions table is empty; does not write PENDING rows unless requested.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.storage.market_memory_db import (
    get_connection,
    get_market_memory_stats,
    init_market_memory_db,
    upsert_outcome,
)
from backend.storage.price_outcome_sanity import (
    DEFAULT_MAX_LATEST_VS_ENTRY_PCT,
    DEFAULT_MAX_STOP_VS_ENTRY_PCT,
    DEFAULT_MAX_TARGET_VS_ENTRY_PCT,
    is_suspicious_price_scale,
)
from backend.utils.config import DATA_DIR

DEFAULT_HOLDING_PERIOD = 'manual'
DEFAULT_PAYLOAD_HOLDING_PERIOD = 'intraday'
DEFAULT_PRICE_HOLDING_PERIOD = 'eod_price'
PAYLOAD_RESOLUTION_SOURCE = 'runtime_payload_resolution'
PRICE_RESOLUTION_SOURCE = 'latest_market_data_price_resolution'
LATEST_MARKET_DATA_PATH = DATA_DIR / 'latest_market_data.json'
LATEST_MARKET_DATA_TIMESTAMP_KEYS = (
    'last_updated',
    'generated_at',
    'timestamp',
    'updated_at',
)


def _log_error(message: str) -> None:
    print(f'[MARKET_MEMORY_OUTCOME] {message}', file=sys.stderr)


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or str(value).strip() == '':
        return None
    text = str(value).strip()
    if len(text) == 10 and text[4] == '-' and text[7] == '-':
        text = f'{text}T00:00:00+00:00'
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _row_to_dict(row: Any) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def get_unresolved_predictions(
    limit: int = 100,
    min_age_hours: int = 0,
    holding_period: str = DEFAULT_HOLDING_PERIOD,
) -> list[dict]:
    """Return predictions without an outcome for the given holding period."""
    try:
        init_market_memory_db()
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT p.*
                FROM predictions p
                LEFT JOIN outcomes o
                  ON o.prediction_id = p.prediction_id
                 AND o.holding_period = ?
                WHERE o.id IS NULL
                ORDER BY p.timestamp ASC
                LIMIT ?
                """,
                (holding_period, max(0, int(limit))),
            ).fetchall()
        finally:
            conn.close()

        predictions = [_row_to_dict(row) for row in rows]
        if min_age_hours <= 0:
            return predictions

        cutoff = datetime.now(timezone.utc) - timedelta(hours=min_age_hours)
        filtered: list[dict] = []
        for prediction in predictions:
            ts = _parse_timestamp(prediction.get('timestamp'))
            if ts is None or ts <= cutoff:
                filtered.append(prediction)
        return filtered
    except Exception as exc:
        _log_error(f'get_unresolved_predictions failed: {exc}')
        return []


def build_outcome_payload(
    prediction: dict,
    price_context: dict | None = None,
    holding_period: str = DEFAULT_HOLDING_PERIOD,
) -> dict:
    """Build canonical outcome upsert payload from prediction and optional price data."""
    prediction_id = prediction.get('prediction_id')
    if not prediction_id:
        return {}

    base_context: dict[str, Any] = {}
    raw_prediction = prediction.get('raw_payload')
    if isinstance(raw_prediction, dict):
        base_context = raw_prediction
    elif isinstance(raw_prediction, str) and raw_prediction.strip():
        try:
            parsed = json.loads(raw_prediction)
            if isinstance(parsed, dict):
                base_context = parsed
        except json.JSONDecodeError:
            pass

    payload: dict[str, Any] = {
        'prediction_id': prediction_id,
        'holding_period': holding_period,
        'market_context': prediction.get('market_context'),
        'vix': prediction.get('vix'),
        'crude': prediction.get('crude'),
        'fii_dii': prediction.get('fii_dii'),
        'global_sentiment': prediction.get('global_sentiment'),
        'india_sentiment': prediction.get('india_sentiment'),
        'sector_strength': prediction.get('sector_strength'),
        'market_regime': prediction.get('market_regime'),
        'raw_payload': {
            'prediction_id': prediction_id,
            'ticker': prediction.get('ticker'),
            'timestamp': prediction.get('timestamp'),
            'source': prediction.get('source'),
            'direction': prediction.get('direction'),
        },
    }

    if price_context is None:
        payload.update({
            'actual_move': None,
            'high': None,
            'low': None,
            'expiry_result': 'UNRESOLVED',
            'resolved_as': 'PENDING',
        })
        return payload

    ctx = price_context if isinstance(price_context, dict) else {}
    payload.update({
        'actual_move': ctx.get('actual_move'),
        'high': ctx.get('high'),
        'low': ctx.get('low'),
        'expiry_result': ctx.get('expiry_result'),
        'resolved_as': ctx.get('resolved_as'),
        'holding_period': ctx.get('holding_period') or holding_period,
        'market_context': ctx.get('market_context', payload.get('market_context')),
        'vix': ctx.get('vix', payload.get('vix')),
        'crude': ctx.get('crude', payload.get('crude')),
        'fii_dii': ctx.get('fii_dii', payload.get('fii_dii')),
        'global_sentiment': ctx.get('global_sentiment', payload.get('global_sentiment')),
        'india_sentiment': ctx.get('india_sentiment', payload.get('india_sentiment')),
        'sector_strength': ctx.get('sector_strength', payload.get('sector_strength')),
        'market_regime': ctx.get('market_regime', payload.get('market_regime')),
    })
    if ctx.get('raw_payload') is not None:
        payload['raw_payload'] = ctx.get('raw_payload')
    elif base_context:
        payload['raw_payload'] = base_context
    return payload


def resolve_prediction_outcome(prediction_id: str, outcome_payload: dict) -> bool:
    """Persist one outcome row; returns False on failure."""
    try:
        payload = dict(outcome_payload)
        payload['prediction_id'] = prediction_id
        if not payload.get('holding_period'):
            payload['holding_period'] = DEFAULT_HOLDING_PERIOD
        return upsert_outcome(payload)
    except Exception as exc:
        _log_error(f'resolve_prediction_outcome failed: {exc}')
        return False


def _is_truthy(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes')
    return bool(value)


def _to_float(value: Any) -> float | None:
    if value is None or str(value).strip() == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_prediction_raw_payload(raw_payload: Any) -> dict:
    if isinstance(raw_payload, dict):
        return dict(raw_payload)
    if isinstance(raw_payload, str) and raw_payload.strip():
        try:
            parsed = json.loads(raw_payload)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _state_is_closed(state: Any) -> bool:
    text = str(state or '').upper()
    return any(token in text for token in ('CLOSED', 'EXPIRED', 'RESOLVED'))


def _expiry_result_from_closed_state(state: Any) -> str:
    text = str(state or '').upper()
    if 'EXPIRED' in text:
        return 'EXPIRED'
    if 'RESOLVED' in text:
        return 'RESOLVED'
    if 'CLOSED' in text:
        return 'CLOSED'
    return 'CLOSED'


def resolve_outcome_from_payload(
    prediction: dict,
    *,
    holding_period: str = DEFAULT_PAYLOAD_HOLDING_PERIOD,
    raw_payload: dict | None = None,
) -> dict | None:
    """
    Derive an evidence-backed outcome payload from prediction raw_payload fields.

    Returns None when there is insufficient evidence (never PENDING).
    """
    prediction_id = prediction.get('prediction_id')
    if not prediction_id:
        return None

    payload = raw_payload if raw_payload is not None else parse_prediction_raw_payload(
        prediction.get('raw_payload'),
    )
    if not payload:
        return None

    resolved_as: str | None = None
    expiry_result: str | None = None

    if _is_truthy(payload.get('target_hit')):
        resolved_as = 'WIN'
        expiry_result = 'TARGET_HIT'
    elif _is_truthy(payload.get('stop_loss_hit')):
        resolved_as = 'LOSS'
        expiry_result = 'STOP_LOSS_HIT'
    elif _state_is_closed(payload.get('state')) and payload.get('change_1d_pct') is not None:
        change = _to_float(payload.get('change_1d_pct'))
        if change is None:
            return None
        direction = str(prediction.get('direction') or '').upper()
        if direction == 'BULLISH':
            if change > 0:
                resolved_as = 'WIN'
            elif change < 0:
                resolved_as = 'LOSS'
            else:
                resolved_as = 'NEUTRAL'
        elif direction == 'BEARISH':
            if change < 0:
                resolved_as = 'WIN'
            elif change > 0:
                resolved_as = 'LOSS'
            else:
                resolved_as = 'NEUTRAL'
        else:
            resolved_as = 'NEUTRAL'
        expiry_result = _expiry_result_from_closed_state(payload.get('state'))
    else:
        return None

    return {
        'prediction_id': prediction_id,
        'actual_move': _to_float(payload.get('change_1d_pct')),
        'high': _to_float(payload.get('max_gain_pct')),
        'low': _to_float(payload.get('max_loss_pct')),
        'expiry_result': expiry_result,
        'resolved_as': resolved_as,
        'holding_period': holding_period,
        'market_regime': prediction.get('market_regime'),
        'raw_payload': {
            'source': PAYLOAD_RESOLUTION_SOURCE,
            'prediction_raw_payload': payload,
        },
    }


def get_predictions_for_payload_resolution(limit: int = 100) -> list[dict]:
    """Return predictions ordered by timestamp for payload-based outcome resolution."""
    try:
        init_market_memory_db()
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM predictions
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (max(0, int(limit)),),
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_dict(row) for row in rows]
    except Exception as exc:
        _log_error(f'get_predictions_for_payload_resolution failed: {exc}')
        return []


def resolve_outcomes_from_payloads(
    limit: int = 100,
    dry_run: bool = False,
    holding_period: str = DEFAULT_PAYLOAD_HOLDING_PERIOD,
    verbose: bool = False,
) -> dict[str, Any]:
    """Scan predictions and upsert outcomes when raw_payload contains result evidence."""
    summary: dict[str, Any] = {
        'dry_run': dry_run,
        'holding_period': holding_period,
        'limit': limit,
        'predictions_checked': 0,
        'resolved': 0,
        'skipped': 0,
        'written': 0,
        'errors': 0,
        'stats_before': get_market_memory_stats(),
        'resolved_by': {
            'TARGET_HIT': 0,
            'STOP_LOSS_HIT': 0,
            'CLOSED_STATE': 0,
        },
        'resolved_ids': [],
        'skipped_ids': [],
    }

    try:
        predictions = get_predictions_for_payload_resolution(limit=limit)
        summary['predictions_checked'] = len(predictions)

        for prediction in predictions:
            prediction_id = prediction.get('prediction_id')
            outcome_payload = resolve_outcome_from_payload(
                prediction,
                holding_period=holding_period,
            )
            if not outcome_payload:
                summary['skipped'] += 1
                if prediction_id:
                    summary['skipped_ids'].append(prediction_id)
                if verbose and prediction_id:
                    print(f'[PAYLOAD_OUTCOMES] skip {prediction_id}: no evidence')
                continue

            summary['resolved'] += 1
            if prediction_id:
                summary['resolved_ids'].append(prediction_id)

            expiry_result = outcome_payload.get('expiry_result')
            if expiry_result == 'TARGET_HIT':
                summary['resolved_by']['TARGET_HIT'] += 1
            elif expiry_result == 'STOP_LOSS_HIT':
                summary['resolved_by']['STOP_LOSS_HIT'] += 1
            else:
                summary['resolved_by']['CLOSED_STATE'] += 1

            if verbose and prediction_id:
                print(
                    f'[PAYLOAD_OUTCOMES] resolve {prediction_id}: '
                    f'{outcome_payload.get("resolved_as")}/{expiry_result}'
                )

            if dry_run:
                continue

            if resolve_prediction_outcome(prediction_id, outcome_payload):
                summary['written'] += 1
            else:
                summary['errors'] += 1

        summary['stats_after'] = get_market_memory_stats()
        return summary
    except Exception as exc:
        _log_error(f'resolve_outcomes_from_payloads failed: {exc}')
        summary['errors'] += 1
        summary['stats_after'] = get_market_memory_stats()
        return summary


def resolve_pending_outcomes(
    limit: int = 100,
    dry_run: bool = True,
    write_pending: bool = False,
    holding_period: str = DEFAULT_HOLDING_PERIOD,
    min_age_hours: int = 0,
) -> dict:
    """
    Scan unresolved predictions and optionally write PENDING/manual outcomes.

    By default (dry_run=True, write_pending=False) nothing is written.
    """
    summary: dict[str, Any] = {
        'dry_run': dry_run,
        'write_pending': write_pending,
        'holding_period': holding_period,
        'limit': limit,
        'min_age_hours': min_age_hours,
        'stats_before': get_market_memory_stats(),
        'unresolved_count': 0,
        'examined': 0,
        'written': 0,
        'skipped': 0,
        'errors': 0,
        'prediction_ids': [],
    }

    try:
        unresolved = get_unresolved_predictions(
            limit=limit,
            min_age_hours=min_age_hours,
            holding_period=holding_period,
        )
        summary['unresolved_count'] = len(unresolved)
        summary['examined'] = len(unresolved)

        if not unresolved:
            summary['stats_after'] = get_market_memory_stats()
            return summary

        should_write = write_pending and not dry_run
        for prediction in unresolved:
            prediction_id = prediction.get('prediction_id')
            if not prediction_id:
                summary['skipped'] += 1
                continue
            summary['prediction_ids'].append(prediction_id)

            if not should_write:
                continue

            outcome_payload = build_outcome_payload(
                prediction,
                price_context=None,
                holding_period=holding_period,
            )
            if not outcome_payload:
                summary['errors'] += 1
                continue
            if resolve_prediction_outcome(prediction_id, outcome_payload):
                summary['written'] += 1
            else:
                summary['errors'] += 1

        summary['stats_after'] = get_market_memory_stats()
        return summary
    except Exception as exc:
        _log_error(f'resolve_pending_outcomes failed: {exc}')
        summary['errors'] += 1
        summary['stats_after'] = get_market_memory_stats()
        return summary


def load_latest_market_data(path: Path | str | None = None) -> dict | None:
    """Load latest_market_data.json; returns None if missing or invalid."""
    file_path = Path(path) if path is not None else LATEST_MARKET_DATA_PATH
    try:
        if not file_path.is_file():
            return None
        text = file_path.read_text(encoding='utf-8')
        if not text.strip():
            return None
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except (OSError, json.JSONDecodeError) as exc:
        _log_error(f'load_latest_market_data failed: {exc}')
        return None


def get_latest_market_data_timestamp(data: dict) -> datetime | None:
    """Parse the freshest timestamp field from latest_market_data."""
    if not isinstance(data, dict):
        return None
    for key in LATEST_MARKET_DATA_TIMESTAMP_KEYS:
        parsed = _parse_timestamp(data.get(key))
        if parsed is not None:
            return parsed
    prices = data.get('prices')
    if isinstance(prices, dict):
        newest: datetime | None = None
        for entry in prices.values():
            if not isinstance(entry, dict):
                continue
            parsed = _parse_timestamp(entry.get('validated_at'))
            if parsed is None:
                continue
            if newest is None or parsed > newest:
                newest = parsed
        return newest
    return None


def latest_market_data_age_hours(data: dict, *, now: datetime | None = None) -> float | None:
    """Return age of latest_market_data in hours, or None if timestamp unknown."""
    ts = get_latest_market_data_timestamp(data)
    if ts is None:
        return None
    reference = now or datetime.now(timezone.utc)
    delta = reference - ts
    return max(0.0, delta.total_seconds() / 3600.0)


def is_latest_market_data_stale(
    data: dict,
    *,
    max_age_hours: float = 24.0,
    allow_stale: bool = False,
    now: datetime | None = None,
) -> bool:
    """True when data is too old or has no parseable timestamp (unless allow_stale)."""
    if allow_stale:
        return False
    ts = get_latest_market_data_timestamp(data)
    if ts is None:
        return True
    age = latest_market_data_age_hours(data, now=now)
    if age is None:
        return True
    return age > float(max_age_hours)


def lookup_latest_price(data: dict, ticker: str) -> float | None:
    """
    Resolve latest price for ticker from latest_market_data prices dict.

    Keys match symbol names (e.g. RELIANCE); each value may be a number or
    object with a price field.
    """
    if not isinstance(data, dict) or not ticker:
        return None
    prices = data.get('prices')
    if not isinstance(prices, dict):
        return None

    symbol = str(ticker).strip().upper()
    match_key: str | None = None
    if symbol in prices:
        match_key = symbol
    else:
        for key in prices:
            if str(key).strip().upper() == symbol:
                match_key = key
                break

    if match_key is None:
        return None

    entry = prices.get(match_key)
    if isinstance(entry, (int, float)) and not isinstance(entry, bool):
        return float(entry)
    if isinstance(entry, dict):
        for field in ('price', 'last_price', 'ltp', 'close'):
            val = _to_float(entry.get(field))
            if val is not None:
                return val
    return _to_float(entry)


def _parse_signal_stack(prediction: dict) -> dict:
    stack = prediction.get('signal_stack')
    if isinstance(stack, dict):
        return dict(stack)
    if isinstance(stack, str) and stack.strip():
        try:
            parsed = json.loads(stack)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def extract_prediction_price_context(prediction: dict) -> dict | None:
    """
    Pull ticker, direction, entry/target/stop from prediction row + raw_payload.

    Returns None when required fields cannot be resolved.
    """
    ticker = prediction.get('ticker')
    if not ticker or not str(ticker).strip():
        return None

    raw = parse_prediction_raw_payload(prediction.get('raw_payload'))
    stack = _parse_signal_stack(prediction)
    merged: dict[str, Any] = {**stack, **raw}

    entry_price = _to_float(
        merged.get('entry_price')
        or merged.get('current_price')
        or merged.get('price')
        or merged.get('close'),
    )
    target_price = _to_float(merged.get('target_price') or merged.get('target'))
    stop_loss = _to_float(merged.get('stop_loss') or merged.get('stop'))

    direction = str(prediction.get('direction') or '').strip().upper()
    if direction not in ('BULLISH', 'BEARISH'):
        from backend.storage.market_memory_capture import infer_direction_from_prices

        inferred = infer_direction_from_prices(merged)
        direction = inferred or ''

    if direction not in ('BULLISH', 'BEARISH'):
        return None
    if entry_price is None:
        return None

    return {
        'ticker': str(ticker).strip().upper(),
        'direction': direction,
        'entry_price': entry_price,
        'target_price': target_price,
        'stop_loss': stop_loss,
    }


def resolve_outcome_from_prices(
    prediction: dict,
    latest_price: float,
    *,
    price_context: dict | None = None,
    holding_period: str = DEFAULT_PRICE_HOLDING_PERIOD,
    latest_market_data_timestamp: str | None = None,
) -> dict | None:
    """
    Derive WIN/LOSS outcome when latest price crosses target or stop.

    Returns None when evidence is insufficient (never PENDING).
    """
    prediction_id = prediction.get('prediction_id')
    if not prediction_id:
        return None

    ctx = price_context if price_context is not None else extract_prediction_price_context(
        prediction,
    )
    if not ctx:
        return None

    entry_price = ctx.get('entry_price')
    target_price = ctx.get('target_price')
    stop_loss = ctx.get('stop_loss')
    direction = ctx.get('direction')

    if entry_price is None or direction not in ('BULLISH', 'BEARISH'):
        return None
    if target_price is None or stop_loss is None:
        return None

    try:
        latest = float(latest_price)
    except (TypeError, ValueError):
        return None

    resolved_as: str | None = None
    expiry_result: str | None = None

    if direction == 'BULLISH':
        if latest >= target_price:
            resolved_as = 'WIN'
            expiry_result = 'TARGET_HIT_BY_PRICE'
        elif latest <= stop_loss:
            resolved_as = 'LOSS'
            expiry_result = 'STOP_LOSS_HIT_BY_PRICE'
        else:
            return None
    else:
        if latest <= target_price:
            resolved_as = 'WIN'
            expiry_result = 'TARGET_HIT_BY_PRICE'
        elif latest >= stop_loss:
            resolved_as = 'LOSS'
            expiry_result = 'STOP_LOSS_HIT_BY_PRICE'
        else:
            return None

    actual_move: float | None = None
    if entry_price:
        actual_move = ((latest - entry_price) / entry_price) * 100.0

    return {
        'prediction_id': prediction_id,
        'actual_move': actual_move,
        'high': latest if direction == 'BULLISH' else None,
        'low': latest if direction == 'BEARISH' else None,
        'expiry_result': expiry_result,
        'resolved_as': resolved_as,
        'holding_period': holding_period,
        'market_regime': prediction.get('market_regime'),
        'raw_payload': {
            'source': PRICE_RESOLUTION_SOURCE,
            'latest_price': latest,
            'entry_price': entry_price,
            'target_price': target_price,
            'stop_loss': stop_loss,
            'latest_market_data_timestamp': latest_market_data_timestamp,
        },
    }


def resolve_outcomes_from_prices(
    limit: int = 100,
    dry_run: bool = False,
    holding_period: str = DEFAULT_PRICE_HOLDING_PERIOD,
    verbose: bool = False,
    *,
    market_data: dict | None = None,
    market_data_path: Path | str | None = None,
    allow_stale: bool = False,
    max_age_hours: float = 24.0,
    allow_suspicious: bool = False,
    max_latest_vs_entry_pct: float = DEFAULT_MAX_LATEST_VS_ENTRY_PCT,
    max_target_vs_entry_pct: float = DEFAULT_MAX_TARGET_VS_ENTRY_PCT,
    max_stop_vs_entry_pct: float = DEFAULT_MAX_STOP_VS_ENTRY_PCT,
) -> dict[str, Any]:
    """Scan predictions and upsert outcomes when latest price hits target or stop."""
    summary: dict[str, Any] = {
        'dry_run': dry_run,
        'holding_period': holding_period,
        'limit': limit,
        'allow_stale': allow_stale,
        'max_age_hours': max_age_hours,
        'latest_market_data_age_hours': None,
        'latest_market_data_stale': False,
        'latest_market_data_invalid': False,
        'predictions_checked': 0,
        'resolved': 0,
        'skipped': 0,
        'written': 0,
        'errors': 0,
        'stats_before': get_market_memory_stats(),
        'resolved_by': {
            'TARGET_HIT_BY_PRICE': 0,
            'STOP_LOSS_HIT_BY_PRICE': 0,
        },
        'resolved_ids': [],
        'skipped_ids': [],
        'skip_reasons': {
            'missing_price_context': 0,
            'missing_latest_price': 0,
            'no_price_evidence': 0,
            'stale_market_data': 0,
            'invalid_market_data': 0,
            'suspicious_price_scale': 0,
        },
        'allow_suspicious': allow_suspicious,
        'max_latest_vs_entry_pct': max_latest_vs_entry_pct,
        'max_target_vs_entry_pct': max_target_vs_entry_pct,
        'max_stop_vs_entry_pct': max_stop_vs_entry_pct,
    }

    try:
        data = market_data if market_data is not None else load_latest_market_data(
            market_data_path,
        )
        if not data:
            summary['latest_market_data_invalid'] = True
            summary['latest_market_data_stale'] = True
            summary['skip_reasons']['invalid_market_data'] = 1
            summary['stats_after'] = get_market_memory_stats()
            return summary

        summary['latest_market_data_age_hours'] = latest_market_data_age_hours(data)
        stale = is_latest_market_data_stale(
            data,
            max_age_hours=max_age_hours,
            allow_stale=allow_stale,
        )
        summary['latest_market_data_stale'] = stale
        if stale:
            summary['skip_reasons']['stale_market_data'] = 1
            summary['stats_after'] = get_market_memory_stats()
            return summary

        ts = get_latest_market_data_timestamp(data)
        ts_text = ts.isoformat() if ts is not None else None

        predictions = get_predictions_for_payload_resolution(limit=limit)
        summary['predictions_checked'] = len(predictions)

        for prediction in predictions:
            prediction_id = prediction.get('prediction_id')
            ctx = extract_prediction_price_context(prediction)
            if not ctx:
                summary['skipped'] += 1
                summary['skip_reasons']['missing_price_context'] += 1
                if prediction_id:
                    summary['skipped_ids'].append(prediction_id)
                if verbose and prediction_id:
                    print(f'[PRICE_OUTCOMES] skip {prediction_id}: missing context')
                continue

            latest = lookup_latest_price(data, ctx['ticker'])
            if latest is None:
                summary['skipped'] += 1
                summary['skip_reasons']['missing_latest_price'] += 1
                if prediction_id:
                    summary['skipped_ids'].append(prediction_id)
                if verbose and prediction_id:
                    print(
                        f'[PRICE_OUTCOMES] skip {prediction_id}: '
                        f'no latest price for {ctx["ticker"]}',
                    )
                continue

            if not allow_suspicious and is_suspicious_price_scale(
                entry_price=ctx.get('entry_price'),
                latest_price=latest,
                target_price=ctx.get('target_price'),
                stop_loss=ctx.get('stop_loss'),
                max_latest_vs_entry_pct=max_latest_vs_entry_pct,
                max_target_vs_entry_pct=max_target_vs_entry_pct,
                max_stop_vs_entry_pct=max_stop_vs_entry_pct,
            ):
                summary['skipped'] += 1
                summary['skip_reasons']['suspicious_price_scale'] += 1
                if prediction_id:
                    summary['skipped_ids'].append(prediction_id)
                if verbose and prediction_id:
                    print(
                        f'[PRICE_OUTCOMES] skip {prediction_id}: '
                        'suspicious_price_scale',
                    )
                continue

            outcome_payload = resolve_outcome_from_prices(
                prediction,
                latest,
                price_context=ctx,
                holding_period=holding_period,
                latest_market_data_timestamp=ts_text,
            )
            if not outcome_payload:
                summary['skipped'] += 1
                summary['skip_reasons']['no_price_evidence'] += 1
                if prediction_id:
                    summary['skipped_ids'].append(prediction_id)
                if verbose and prediction_id:
                    print(
                        f'[PRICE_OUTCOMES] skip {prediction_id}: '
                        'price between entry/target/stop',
                    )
                continue

            summary['resolved'] += 1
            if prediction_id:
                summary['resolved_ids'].append(prediction_id)

            expiry_result = outcome_payload.get('expiry_result')
            if expiry_result == 'TARGET_HIT_BY_PRICE':
                summary['resolved_by']['TARGET_HIT_BY_PRICE'] += 1
            elif expiry_result == 'STOP_LOSS_HIT_BY_PRICE':
                summary['resolved_by']['STOP_LOSS_HIT_BY_PRICE'] += 1

            if verbose and prediction_id:
                print(
                    f'[PRICE_OUTCOMES] resolve {prediction_id}: '
                    f'{outcome_payload.get("resolved_as")}/{expiry_result} '
                    f'latest={latest}',
                )

            if dry_run:
                continue

            if resolve_prediction_outcome(prediction_id, outcome_payload):
                summary['written'] += 1
            else:
                summary['errors'] += 1

        summary['stats_after'] = get_market_memory_stats()
        return summary
    except Exception as exc:
        _log_error(f'resolve_outcomes_from_prices failed: {exc}')
        summary['errors'] += 1
        summary['stats_after'] = get_market_memory_stats()
        return summary
