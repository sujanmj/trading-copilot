"""
Read-only learning summary for canonical_market_memory.db.

Joins predictions with outcomes to compute win rates and grouped performance.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.storage.market_memory_db import get_connection, get_market_memory_stats

LOW_SAMPLE_THRESHOLD = 5

WIN_TOKENS = frozenset({'WIN', 'TARGET_HIT', 'TARGET_HIT_BY_PRICE'})
LOSS_TOKENS = frozenset({'LOSS', 'STOP_LOSS_HIT', 'STOP_LOSS_HIT_BY_PRICE'})

VALID_GROUP_BY = frozenset({
    'confidence',
    'source',
    'signal_type',
    'horizon',
    'ticker',
    'broker_consensus',
})


def _parse_json_field(value: object) -> dict | list | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_win(resolved_as: str | None) -> bool:
    if not resolved_as:
        return False
    token = str(resolved_as).strip().upper()
    if token in WIN_TOKENS:
        return True
    return token.startswith('WIN')


def _is_loss(resolved_as: str | None) -> bool:
    if not resolved_as:
        return False
    token = str(resolved_as).strip().upper()
    if token in LOSS_TOKENS:
        return True
    return token.startswith('LOSS')


def _safe_avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _safe_win_rate(wins: int, losses: int) -> float | None:
    total = wins + losses
    if total <= 0:
        return None
    return wins / total


def _group_warnings(resolved: int) -> list[str]:
    if resolved < LOW_SAMPLE_THRESHOLD:
        return ['low_sample_size']
    return []


def _metric_block(
    *,
    resolved: int,
    wins: int,
    losses: int,
    actual_moves: list[float],
) -> dict[str, Any]:
    return {
        'resolved': resolved,
        'wins': wins,
        'losses': losses,
        'win_rate': _safe_win_rate(wins, losses),
        'avg_actual_move': _safe_avg(actual_moves),
        'warnings': _group_warnings(resolved),
    }


def _empty_metric_block() -> dict[str, Any]:
    return _metric_block(resolved=0, wins=0, losses=0, actual_moves=[])


def _extract_signal_type(signal_stack: object, raw_payload: object) -> str:
    for container in (_parse_json_field(signal_stack), _parse_json_field(raw_payload)):
        if not isinstance(container, dict):
            continue
        val = container.get('signal_type')
        if val is not None and str(val).strip():
            return str(val).strip()
    return 'UNKNOWN'


def _extract_horizon(signal_stack: object, raw_payload: object) -> str:
    for container in (_parse_json_field(signal_stack), _parse_json_field(raw_payload)):
        if not isinstance(container, dict):
            continue
        val = container.get('prediction_horizon')
        if val is not None and str(val).strip():
            return str(val).strip()
    return 'UNKNOWN'


def _extract_broker_consensus(signal_stack: object, raw_payload: object) -> str:
    for container in (_parse_json_field(signal_stack), _parse_json_field(raw_payload)):
        if not isinstance(container, dict):
            continue
        consensus = container.get('broker_consensus')
        if not isinstance(consensus, dict):
            continue
        direction = consensus.get('agreement_direction')
        if direction is not None and str(direction).strip():
            return str(direction).strip().upper()
    return 'UNKNOWN'


def _group_key(row: dict[str, Any], group_by: str) -> str:
    if group_by == 'confidence':
        val = row.get('confidence_label')
        return str(val).strip().upper() if val else 'UNKNOWN'
    if group_by == 'source':
        val = row.get('source')
        return str(val).strip() if val else 'UNKNOWN'
    if group_by == 'signal_type':
        return _extract_signal_type(row.get('signal_stack'), row.get('raw_payload'))
    if group_by == 'horizon':
        return _extract_horizon(row.get('signal_stack'), row.get('raw_payload'))
    if group_by == 'ticker':
        val = row.get('ticker')
        return str(val).strip().upper() if val else 'UNKNOWN'
    if group_by == 'broker_consensus':
        return _extract_broker_consensus(row.get('signal_stack'), row.get('raw_payload'))
    return 'UNKNOWN'


def _row_within_limit(timestamp: str | None, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    dt = _parse_timestamp(timestamp)
    if dt is None:
        return True
    return dt >= cutoff


def _fetch_joined_rows(limit_days: int | None = None) -> list[dict[str, Any]]:
    cutoff: datetime | None = None
    if limit_days is not None and limit_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(limit_days))

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                p.prediction_id,
                p.ticker,
                p.timestamp,
                p.source,
                p.confidence_label,
                p.signal_stack,
                p.raw_payload,
                o.resolved_as,
                o.actual_move,
                o.holding_period
            FROM predictions p
            LEFT JOIN outcomes o ON p.prediction_id = o.prediction_id
            ORDER BY p.timestamp ASC
            """
        ).fetchall()
    finally:
        conn.close()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if not _row_within_limit(item.get('timestamp'), cutoff):
            continue
        result.append(item)
    return result


def _aggregate_resolved_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}

    for row in rows:
        if row.get('resolved_as') is None:
            continue
        key = row.get('_group_key', 'ALL')
        bucket = buckets.setdefault(
            key,
            {'resolved': 0, 'wins': 0, 'losses': 0, 'actual_moves': []},
        )
        bucket['resolved'] += 1
        if _is_win(row.get('resolved_as')):
            bucket['wins'] += 1
        elif _is_loss(row.get('resolved_as')):
            bucket['losses'] += 1
        move = row.get('actual_move')
        if move is not None:
            try:
                bucket['actual_moves'].append(float(move))
            except (TypeError, ValueError):
                pass

    output: dict[str, Any] = {}
    for key, bucket in buckets.items():
        output[key] = _metric_block(
            resolved=bucket['resolved'],
            wins=bucket['wins'],
            losses=bucket['losses'],
            actual_moves=bucket['actual_moves'],
        )
    return output


def _compute_overall(rows: list[dict[str, Any]]) -> dict[str, Any]:
    prediction_ids = {row['prediction_id'] for row in rows}
    resolved_rows = [row for row in rows if row.get('resolved_as') is not None]
    resolved_prediction_ids = {row['prediction_id'] for row in resolved_rows}

    wins = sum(1 for row in resolved_rows if _is_win(row.get('resolved_as')))
    losses = sum(1 for row in resolved_rows if _is_loss(row.get('resolved_as')))
    actual_moves: list[float] = []
    for row in resolved_rows:
        move = row.get('actual_move')
        if move is not None:
            try:
                actual_moves.append(float(move))
            except (TypeError, ValueError):
                pass

    overall = {
        'total_predictions': len(prediction_ids),
        'resolved_outcomes': len(resolved_rows),
        'unresolved_predictions': len(prediction_ids - resolved_prediction_ids),
        'wins': wins,
        'losses': losses,
        'win_rate': _safe_win_rate(wins, losses),
        'avg_actual_move': _safe_avg(actual_moves),
        'warnings': _group_warnings(len(resolved_rows)),
    }
    return overall


def get_grouped_performance(group_by: str, *, limit_days: int | None = None) -> dict:
    """Return performance metrics grouped by dimension."""
    normalized = str(group_by or '').strip().lower()
    if normalized not in VALID_GROUP_BY:
        return {
            'ok': False,
            'error': f'invalid group_by: {group_by}',
            'valid_group_by': sorted(VALID_GROUP_BY),
        }

    rows = _fetch_joined_rows(limit_days=limit_days)
    resolved_rows = [row for row in rows if row.get('resolved_as') is not None]
    for row in resolved_rows:
        row['_group_key'] = _group_key(row, normalized)

    grouped = _aggregate_resolved_rows(resolved_rows)
    groups = [
        {'key': key, **metrics}
        for key, metrics in sorted(grouped.items(), key=lambda item: (-item[1]['resolved'], item[0]))
    ]

    return {
        'ok': True,
        'group_by': normalized,
        'limit_days': limit_days,
        'groups': groups,
    }


def get_ticker_performance(ticker: str, *, limit_days: int | None = None) -> dict:
    """Return performance metrics for a single ticker (outcomes only)."""
    normalized = str(ticker or '').strip().upper()
    if not normalized:
        return {'ok': False, 'error': 'ticker is required'}

    rows = _fetch_joined_rows(limit_days=limit_days)
    resolved_rows = [
        row for row in rows
        if row.get('resolved_as') is not None and str(row.get('ticker') or '').upper() == normalized
    ]

    if not resolved_rows:
        return {
            'ok': True,
            'ticker': normalized,
            'limit_days': limit_days,
            'performance': _empty_metric_block(),
            'message': 'no resolved outcomes for ticker',
        }

    wins = sum(1 for row in resolved_rows if _is_win(row.get('resolved_as')))
    losses = sum(1 for row in resolved_rows if _is_loss(row.get('resolved_as')))
    actual_moves: list[float] = []
    for row in resolved_rows:
        move = row.get('actual_move')
        if move is not None:
            try:
                actual_moves.append(float(move))
            except (TypeError, ValueError):
                pass

    return {
        'ok': True,
        'ticker': normalized,
        'limit_days': limit_days,
        'performance': _metric_block(
            resolved=len(resolved_rows),
            wins=wins,
            losses=losses,
            actual_moves=actual_moves,
        ),
    }


def get_learning_summary(limit_days: int | None = None) -> dict:
    """Return overall and grouped learning metrics from market memory."""
    stats = get_market_memory_stats()
    if not stats.get('db_exists'):
        return {
            'ok': True,
            'db_path': stats.get('db_path'),
            'limit_days': limit_days,
            'overall': {
                'total_predictions': 0,
                'resolved_outcomes': 0,
                'unresolved_predictions': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': None,
                'avg_actual_move': None,
                'warnings': ['db_missing'],
            },
            'by_confidence_label': {},
            'by_source': {},
            'by_signal_type': {},
            'by_prediction_horizon': {},
            'by_ticker': {},
            'by_broker_consensus': {},
        }

    rows = _fetch_joined_rows(limit_days=limit_days)
    overall = _compute_overall(rows)
    resolved_rows = [row for row in rows if row.get('resolved_as') is not None]

    def _build_group_map(group_by: str) -> dict[str, Any]:
        keyed_rows = []
        for row in resolved_rows:
            copy = dict(row)
            copy['_group_key'] = _group_key(copy, group_by)
            keyed_rows.append(copy)
        return _aggregate_resolved_rows(keyed_rows)

    return {
        'ok': True,
        'db_path': stats.get('db_path'),
        'limit_days': limit_days,
        'overall': overall,
        'by_confidence_label': _build_group_map('confidence'),
        'by_source': _build_group_map('source'),
        'by_signal_type': _build_group_map('signal_type'),
        'by_prediction_horizon': _build_group_map('horizon'),
        'by_ticker': _build_group_map('ticker'),
        'by_broker_consensus': _build_group_map('broker_consensus'),
    }
