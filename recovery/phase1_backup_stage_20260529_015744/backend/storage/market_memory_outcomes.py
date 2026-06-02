"""
Resolve prediction outcomes into canonical_market_memory.db.

Safe when predictions table is empty; does not write PENDING rows unless requested.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.storage.market_memory_db import (
    get_connection,
    get_market_memory_stats,
    init_market_memory_db,
    upsert_outcome,
)

DEFAULT_HOLDING_PERIOD = 'manual'


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
