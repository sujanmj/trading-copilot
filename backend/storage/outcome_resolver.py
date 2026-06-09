"""
Signal-quality outcome resolver — Stage 49A.

Resolves pending canonical predictions when valid reference/evaluation prices exist.
Idempotent per (prediction_id, holding_period). Does not fake outcomes without prices.
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
from backend.storage.market_memory_outcomes import (
    _parse_signal_stack,
    _parse_timestamp,
    _to_float,
    load_latest_market_data,
    lookup_latest_price,
    parse_prediction_raw_payload,
)
from backend.utils.config import DATA_DIR

RESOLVER_VERSION = '49A'
SIGNAL_QUALITY_HOLDING_PERIOD = 'signal_quality'
CALIBRATION_MIN_SAMPLE = 20
OUTCOME_RESOLVER_STATE_FILE = DATA_DIR / 'outcome_resolver_last_run.json'
MEMORY_CACHE_FILE = DATA_DIR / 'market_memory_dashboard_cache.json'

BULLISH_HIT_PCT = 0.75
BULLISH_MISS_PCT = -0.75
BEARISH_HIT_PCT = -0.50
BEARISH_MISS_PCT = 1.00
NEUTRAL_ZONE_ENABLED = True

RESOLVER_SOURCE = 'outcome_resolver_49a'

HORIZON_MIN_HOURS = {
    'intraday': 6,
    'next_day': 18,
    'swing_5d': 96,
    'UNKNOWN': 18,
}

BEARISH_SIGNAL_TOKENS = frozenset({
    'AVOID', 'REJECTED', 'REJECT', 'BEARISH', 'SHORT', 'BREAKDOWN', 'SELL',
})
BULLISH_SIGNAL_TOKENS = frozenset({
    'WATCH', 'WATCH_FOR_ENTRY', 'BUY', 'BULLISH', 'BUY_CANDIDATE', 'LONG',
})


def _log(message: str) -> None:
    print(f'[OUTCOME_RESOLVER] {message}', flush=True)


def _log_error(message: str) -> None:
    print(f'[OUTCOME_RESOLVER] {message}', file=sys.stderr, flush=True)


def _extract_horizon(prediction: dict) -> str:
    raw = parse_prediction_raw_payload(prediction.get('raw_payload'))
    stack = _parse_signal_stack(prediction)
    for container in (stack, raw):
        val = container.get('prediction_horizon') or container.get('horizon')
        if val is not None and str(val).strip():
            return str(val).strip()
    return 'next_day'


def _extract_signal_type(prediction: dict) -> str:
    raw = parse_prediction_raw_payload(prediction.get('raw_payload'))
    stack = _parse_signal_stack(prediction)
    for container in (stack, raw):
        val = container.get('signal_type')
        if val is not None and str(val).strip():
            return str(val).strip().upper()
    direction = str(prediction.get('direction') or '').strip().upper()
    if direction == 'BEARISH':
        return 'AVOID'
    if direction == 'BULLISH':
        return 'WATCH_FOR_ENTRY'
    return 'UNKNOWN'


def is_bearish_signal(prediction: dict) -> bool:
    signal_type = _extract_signal_type(prediction)
    if signal_type in BEARISH_SIGNAL_TOKENS:
        return True
    if any(token in signal_type for token in ('AVOID', 'REJECT', 'BEARISH', 'SHORT')):
        return True
    direction = str(prediction.get('direction') or '').strip().upper()
    return direction == 'BEARISH'


def evaluate_return_outcome(return_pct: float, *, bearish: bool) -> tuple[str, str]:
    """Return (outcome, outcome_reason) where outcome is hit/miss/neutral."""
    if bearish:
        if return_pct <= BEARISH_HIT_PCT:
            return 'hit', f'return {return_pct:.2f}% <= bearish hit threshold {BEARISH_HIT_PCT}%'
        if return_pct >= BEARISH_MISS_PCT:
            return 'miss', f'return {return_pct:.2f}% >= bearish miss threshold {BEARISH_MISS_PCT}%'
        if NEUTRAL_ZONE_ENABLED:
            return 'neutral', f'return {return_pct:.2f}% inside neutral zone'
        return 'neutral', 'return inside dead-zone'
    if return_pct >= BULLISH_HIT_PCT:
        return 'hit', f'return {return_pct:.2f}% >= bullish hit threshold {BULLISH_HIT_PCT}%'
    if return_pct <= BULLISH_MISS_PCT:
        return 'miss', f'return {return_pct:.2f}% <= bullish miss threshold {BULLISH_MISS_PCT}%'
    if NEUTRAL_ZONE_ENABLED:
        return 'neutral', f'return {return_pct:.2f}% inside neutral zone'
    return 'neutral', 'return inside dead-zone'


def map_outcome_to_resolved_as(outcome: str) -> str:
    token = str(outcome or '').strip().lower()
    if token == 'hit':
        return 'WIN'
    if token == 'miss':
        return 'LOSS'
    if token == 'neutral':
        return 'NEUTRAL'
    return 'UNRESOLVED'


def _reference_price(prediction: dict) -> float | None:
    raw = parse_prediction_raw_payload(prediction.get('raw_payload'))
    stack = _parse_signal_stack(prediction)
    merged = {**stack, **raw}
    return _to_float(
        merged.get('entry_price')
        or merged.get('reference_price')
        or merged.get('current_price')
        or merged.get('price')
        or merged.get('close'),
    )


def _signal_time(prediction: dict) -> datetime | None:
    raw = parse_prediction_raw_payload(prediction.get('raw_payload'))
    for key in ('signal_time', 'created_at', 'timestamp', 'prediction_date'):
        for container in (raw, prediction):
            parsed = _parse_timestamp(container.get(key) if isinstance(container, dict) else None)
            if parsed is not None:
                return parsed
    return _parse_timestamp(prediction.get('timestamp'))


def _horizon_due(signal_time: datetime | None, horizon: str, *, now: datetime | None = None) -> bool:
    if signal_time is None:
        return False
    now = now or datetime.now(timezone.utc)
    min_hours = HORIZON_MIN_HOURS.get(horizon, HORIZON_MIN_HOURS['UNKNOWN'])
    age_h = (now - signal_time).total_seconds() / 3600.0
    return age_h >= float(min_hours)


def _prediction_has_outcome(prediction_id: str, holding_period: str = SIGNAL_QUALITY_HOLDING_PERIOD) -> bool:
    try:
        init_market_memory_db()
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT 1 FROM outcomes
                WHERE prediction_id = ? AND holding_period = ?
                LIMIT 1
                """,
                (prediction_id, holding_period),
            ).fetchone()
            return row is not None
        finally:
            conn.close()
    except Exception:
        return False


def get_pending_predictions(limit: int = 500) -> list[dict]:
    """Predictions without signal_quality outcome."""
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
                  AND p.ticker IS NOT NULL
                  AND TRIM(p.ticker) != ''
                ORDER BY p.timestamp ASC
                LIMIT ?
                """,
                (SIGNAL_QUALITY_HOLDING_PERIOD, max(0, int(limit))),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except Exception as exc:
        _log_error(f'get_pending_predictions failed: {exc}')
        return []


def _count_pending() -> int:
    try:
        init_market_memory_db()
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM predictions p
                LEFT JOIN outcomes o
                  ON o.prediction_id = p.prediction_id
                 AND o.holding_period = ?
                WHERE o.id IS NULL
                """,
                (SIGNAL_QUALITY_HOLDING_PERIOD,),
            ).fetchone()
            return int(row['cnt']) if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def resolve_single_prediction(
    prediction: dict,
    market_data: dict,
    *,
    now: datetime | None = None,
) -> tuple[dict | None, str | None]:
    """
    Build outcome payload for one prediction, or return (None, skip_reason).
    Never returns a payload without valid reference/evaluation prices.
    """
    now = now or datetime.now(timezone.utc)
    prediction_id = prediction.get('prediction_id')
    ticker = str(prediction.get('ticker') or '').strip().upper()
    if not prediction_id or not ticker:
        return None, 'missing_ticker_or_id'

    if _prediction_has_outcome(str(prediction_id)):
        return None, 'already_resolved'

    signal_time = _signal_time(prediction)
    if signal_time is None:
        return None, 'missing_signal_time'

    horizon = _extract_horizon(prediction)
    if not _horizon_due(signal_time, horizon, now=now):
        return None, 'not_due'

    ref_price = _reference_price(prediction)
    if ref_price is None or ref_price <= 0:
        return None, 'missing_reference_price'

    eval_price = lookup_latest_price(market_data, ticker)
    if eval_price is None or eval_price <= 0:
        return None, 'missing_evaluation_price'

    return_pct = ((eval_price - ref_price) / ref_price) * 100.0
    bearish = is_bearish_signal(prediction)
    outcome, outcome_reason = evaluate_return_outcome(return_pct, bearish=bearish)
    resolved_as = map_outcome_to_resolved_as(outcome)
    if resolved_as == 'UNRESOLVED':
        return None, 'unresolved_outcome'

    signal_type = _extract_signal_type(prediction)
    resolved_at = now.isoformat()
    raw_payload = {
        'source': RESOLVER_SOURCE,
        'resolver_version': RESOLVER_VERSION,
        'ticker': ticker,
        'signal_type': signal_type,
        'signal_time': signal_time.isoformat(),
        'horizon': horizon,
        'reference_price': ref_price,
        'evaluation_price': eval_price,
        'benchmark_return': None,
        'return_pct': round(return_pct, 4),
        'outcome': outcome,
        'outcome_reason': outcome_reason,
        'resolved_at': resolved_at,
    }

    return {
        'prediction_id': prediction_id,
        'actual_move': round(return_pct, 4),
        'high': eval_price if not bearish else None,
        'low': eval_price if bearish else None,
        'expiry_result': outcome.upper(),
        'resolved_as': resolved_as,
        'holding_period': SIGNAL_QUALITY_HOLDING_PERIOD,
        'market_regime': prediction.get('market_regime'),
        'raw_payload': raw_payload,
    }, None


def refresh_memory_dashboard_cache(*, limit: int = 50) -> bool:
    """Rebuild market_memory_dashboard_cache.json after resolver writes."""
    try:
        from backend.analytics.market_memory_dashboard import get_market_memory_dashboard

        dashboard = get_market_memory_dashboard(limit=limit)
        if not isinstance(dashboard, dict):
            return False
        MEMORY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_CACHE_FILE.write_text(json.dumps(dashboard, indent=2, default=str), encoding='utf-8')
        return True
    except Exception as exc:
        _log_error(f'refresh_memory_dashboard_cache failed: {exc}')
        return False


def compute_signal_quality_metrics(
    *,
    holding_period: str = SIGNAL_QUALITY_HOLDING_PERIOD,
) -> dict[str, Any]:
    """Aggregate hit rates from signal_quality outcomes."""
    metrics: dict[str, Any] = {
        'resolved': 0,
        'pending': 0,
        'neutral': 0,
        'hit_rate': None,
        'bullish_hit_rate': None,
        'bearish_hit_rate': None,
        'last_resolved_at': None,
    }
    try:
        init_market_memory_db()
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT p.direction, p.raw_payload, p.signal_stack, o.resolved_as, o.raw_payload AS outcome_raw, o.updated_at
                FROM outcomes o
                JOIN predictions p ON p.prediction_id = o.prediction_id
                WHERE o.holding_period = ?
                ORDER BY o.updated_at DESC
                """,
                (holding_period,),
            ).fetchall()
            pending = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM predictions p
                LEFT JOIN outcomes o ON o.prediction_id = p.prediction_id AND o.holding_period = ?
                WHERE o.id IS NULL
                """,
                (holding_period,),
            ).fetchone()
            metrics['pending'] = int(pending['cnt']) if pending else 0
        finally:
            conn.close()

        wins = losses = neutral = 0
        bull_w = bull_t = bear_w = bear_t = 0
        last_resolved = None
        for row in rows:
            item = dict(row)
            metrics['resolved'] += 1
            resolved_as = str(item.get('resolved_as') or '').upper()
            if resolved_as == 'NEUTRAL':
                neutral += 1
            elif resolved_as in ('WIN', 'HIT') or resolved_as.startswith('WIN'):
                wins += 1
            elif resolved_as in ('LOSS', 'MISS') or resolved_as.startswith('LOSS'):
                losses += 1

            pred = {
                'direction': item.get('direction'),
                'raw_payload': item.get('raw_payload'),
                'signal_stack': item.get('signal_stack'),
            }
            bearish = is_bearish_signal(pred)
            is_hit = resolved_as in ('WIN', 'HIT') or str(resolved_as).startswith('WIN')
            if bearish:
                bear_t += 1
                if is_hit:
                    bear_w += 1
            else:
                bull_t += 1
                if is_hit:
                    bull_w += 1

            ts = item.get('updated_at')
            if ts and (last_resolved is None or str(ts) > str(last_resolved)):
                last_resolved = ts

        metrics['neutral'] = neutral
        total_scored = wins + losses
        if total_scored > 0:
            metrics['hit_rate'] = wins / total_scored
        if bull_t > 0:
            metrics['bullish_hit_rate'] = bull_w / bull_t
        if bear_t > 0:
            metrics['bearish_hit_rate'] = bear_w / bear_t
        metrics['last_resolved_at'] = last_resolved
        return metrics
    except Exception as exc:
        _log_error(f'compute_signal_quality_metrics failed: {exc}')
        return metrics


def run_outcome_resolver_once(
    *,
    dry_run: bool = False,
    limit: int = 500,
    market_data: dict | None = None,
    market_data_path: Path | str | None = None,
    refresh_cache: bool = True,
) -> dict[str, Any]:
    """Resolve eligible pending predictions once; idempotent."""
    stats_before = get_market_memory_stats()
    pending_before = _count_pending()
    summary: dict[str, Any] = {
        'dry_run': dry_run,
        'resolver_version': RESOLVER_VERSION,
        'holding_period': SIGNAL_QUALITY_HOLDING_PERIOD,
        'pending_before': pending_before,
        'resolved_new': 0,
        'pending_after': pending_before,
        'skipped_no_price': 0,
        'skipped_not_due': 0,
        'skipped_already_resolved': 0,
        'skipped_other': 0,
        'errors': 0,
        'stats_before': stats_before,
        'resolved_ids': [],
    }

    data = market_data if market_data is not None else load_latest_market_data(market_data_path)
    if not data:
        summary['errors'] = 0
        summary['skipped_no_price'] = pending_before
        summary['pending_after'] = pending_before
        summary['stats_after'] = get_market_memory_stats()
        return summary

    predictions = get_pending_predictions(limit=limit)
    for prediction in predictions:
        payload, skip = resolve_single_prediction(prediction, data)
        if skip == 'already_resolved':
            summary['skipped_already_resolved'] += 1
            continue
        if skip == 'not_due':
            summary['skipped_not_due'] += 1
            continue
        if skip in ('missing_reference_price', 'missing_evaluation_price', 'missing_signal_time'):
            summary['skipped_no_price'] += 1
            continue
        if payload is None:
            summary['skipped_other'] += 1
            continue

        summary['resolved_new'] += 1
        pid = payload.get('prediction_id')
        if pid:
            summary['resolved_ids'].append(pid)

        if dry_run:
            continue

        if upsert_outcome(payload):
            pass
        else:
            summary['errors'] += 1
            summary['resolved_new'] -= 1

    summary['pending_after'] = _count_pending()
    summary['stats_after'] = get_market_memory_stats()

    if not dry_run and summary['resolved_new'] > 0 and refresh_cache:
        refresh_memory_dashboard_cache()

    return summary


def _load_resolver_state() -> dict:
    if not OUTCOME_RESOLVER_STATE_FILE.is_file():
        return {}
    try:
        data = json.loads(OUTCOME_RESOLVER_STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_resolver_state(state: dict) -> None:
    OUTCOME_RESOLVER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTCOME_RESOLVER_STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def run_after_close_outcome_resolver_if_due(*, now: datetime | None = None) -> dict[str, Any]:
    """
    Safe after-close hook — max once per IST calendar day.
    Never raises; returns skip summary on failure.
    """
    now = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        ist = ZoneInfo('Asia/Kolkata')
        now_ist = now.astimezone(ist)
        if now_ist.hour < 15 or (now_ist.hour == 15 and now_ist.minute < 30):
            return {'skipped': 'before_india_close', 'resolved_new': 0}

        day_key = now_ist.date().isoformat()
        state = _load_resolver_state()
        if state.get('last_run_date') == day_key:
            return {'skipped': 'already_ran_today', 'resolved_new': 0}

        summary = run_outcome_resolver_once(refresh_cache=True)
        state['last_run_date'] = day_key
        state['last_summary'] = {
            'resolved_new': summary.get('resolved_new', 0),
            'pending_after': summary.get('pending_after', 0),
            'errors': summary.get('errors', 0),
        }
        _save_resolver_state(state)
        _log(
            f"after-close run resolved_new={summary.get('resolved_new', 0)} "
            f"pending_after={summary.get('pending_after', 0)}",
        )
        return summary
    except Exception as exc:
        _log_error(f'run_after_close_outcome_resolver_if_due failed: {exc}')
        return {'skipped': 'error', 'errors': 1, 'resolved_new': 0}
