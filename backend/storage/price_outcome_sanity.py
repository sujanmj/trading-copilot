"""
Shared price-outcome sanity checks for audit, delete, and resolution.

Detects price-scale mismatches (e.g. entry stored in wrong units vs latest market data).
"""

from __future__ import annotations

import json
from typing import Any

PRICE_EXPIRY_RESULTS = ('TARGET_HIT_BY_PRICE', 'STOP_LOSS_HIT_BY_PRICE')

DEFAULT_MAX_LATEST_VS_ENTRY_PCT = 20.0
DEFAULT_MAX_TARGET_VS_ENTRY_PCT = 30.0
DEFAULT_MAX_STOP_VS_ENTRY_PCT = 30.0


def _parse_json_field(value: Any) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def _to_float(value: Any) -> float | None:
    if value is None or str(value).strip() == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pct_move(from_price: float | None, to_price: float | None) -> float | None:
    if from_price is None or to_price is None or from_price == 0:
        return None
    return ((to_price - from_price) / from_price) * 100.0


def extract_prices(
    outcome_raw: dict | None,
    prediction_raw: dict | None,
    signal_stack: dict | None,
) -> dict[str, float | None]:
    """Prefer outcome raw_payload prices; fall back to prediction/signal_stack."""
    merged_pred: dict[str, Any] = {}
    if signal_stack:
        merged_pred.update(signal_stack)
    if prediction_raw:
        merged_pred.update(prediction_raw)

    entry_keys = ('entry_price', 'current_price', 'price', 'close')
    target_keys = ('target_price', 'target')
    stop_keys = ('stop_loss', 'stop')
    latest_keys = ('latest_price',)

    def _pick(payload: dict | None, keys: tuple[str, ...]) -> float | None:
        if not payload:
            return None
        for key in keys:
            val = _to_float(payload.get(key))
            if val is not None:
                return val
        return None

    entry_price = _pick(outcome_raw, entry_keys)
    if entry_price is None:
        entry_price = _pick(merged_pred, entry_keys)

    target_price = _pick(outcome_raw, target_keys)
    if target_price is None:
        target_price = _pick(merged_pred, target_keys)

    stop_loss = _pick(outcome_raw, stop_keys)
    if stop_loss is None:
        stop_loss = _pick(merged_pred, stop_keys)

    latest_price = _pick(outcome_raw, latest_keys)

    return {
        'entry_price': entry_price,
        'target_price': target_price,
        'stop_loss': stop_loss,
        'latest_price': latest_price,
    }


def check_price_sanity_gates(
    *,
    entry_price: float | None,
    latest_price: float | None,
    target_price: float | None,
    stop_loss: float | None,
    max_latest_vs_entry_pct: float = DEFAULT_MAX_LATEST_VS_ENTRY_PCT,
    max_target_vs_entry_pct: float = DEFAULT_MAX_TARGET_VS_ENTRY_PCT,
    max_stop_vs_entry_pct: float = DEFAULT_MAX_STOP_VS_ENTRY_PCT,
) -> list[str]:
    """
    Return list of failed sanity gate names (empty when all gates pass).

    Gates match price resolution defaults:
      - |latest vs entry| <= max_latest_vs_entry_pct (default 20%)
      - |target vs entry| <= max_target_vs_entry_pct (default 30%)
      - |stop vs entry| <= max_stop_vs_entry_pct (default 30%)
    """
    failures: list[str] = []

    latest_vs_entry = pct_move(entry_price, latest_price)
    if latest_vs_entry is not None and abs(latest_vs_entry) > max_latest_vs_entry_pct:
        failures.append('latest_vs_entry_abs_pct')

    target_vs_entry = pct_move(entry_price, target_price)
    if target_vs_entry is not None and abs(target_vs_entry) > max_target_vs_entry_pct:
        failures.append('target_vs_entry_abs_pct')

    stop_vs_entry = pct_move(entry_price, stop_loss)
    if stop_vs_entry is not None and abs(stop_vs_entry) > max_stop_vs_entry_pct:
        failures.append('stop_vs_entry_abs_pct')

    return failures


def detect_price_outcome_anomalies(
    row: dict[str, Any],
    *,
    max_latest_vs_entry_pct: float = DEFAULT_MAX_LATEST_VS_ENTRY_PCT,
    max_target_vs_entry_pct: float = DEFAULT_MAX_TARGET_VS_ENTRY_PCT,
    max_stop_vs_entry_pct: float = DEFAULT_MAX_STOP_VS_ENTRY_PCT,
) -> list[str]:
    flags: list[str] = []

    entry_price = row.get('entry_price')
    latest_price = row.get('latest_price')
    target_price = row.get('target_price')
    stop_loss = row.get('stop_loss')

    if latest_price is None:
        flags.append('missing_latest_price')
    if entry_price is None:
        flags.append('missing_entry_price')

    gate_failures = check_price_sanity_gates(
        entry_price=entry_price,
        latest_price=latest_price,
        target_price=target_price,
        stop_loss=stop_loss,
        max_latest_vs_entry_pct=max_latest_vs_entry_pct,
        max_target_vs_entry_pct=max_target_vs_entry_pct,
        max_stop_vs_entry_pct=max_stop_vs_entry_pct,
    )
    if gate_failures:
        flags.append('suspicious_price_scale')

    return flags


def is_suspicious_price_scale(
    *,
    entry_price: float | None,
    latest_price: float | None,
    target_price: float | None,
    stop_loss: float | None,
    max_latest_vs_entry_pct: float = DEFAULT_MAX_LATEST_VS_ENTRY_PCT,
    max_target_vs_entry_pct: float = DEFAULT_MAX_TARGET_VS_ENTRY_PCT,
    max_stop_vs_entry_pct: float = DEFAULT_MAX_STOP_VS_ENTRY_PCT,
) -> bool:
    return bool(
        check_price_sanity_gates(
            entry_price=entry_price,
            latest_price=latest_price,
            target_price=target_price,
            stop_loss=stop_loss,
            max_latest_vs_entry_pct=max_latest_vs_entry_pct,
            max_target_vs_entry_pct=max_target_vs_entry_pct,
            max_stop_vs_entry_pct=max_stop_vs_entry_pct,
        ),
    )


def fetch_price_outcomes(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            o.prediction_id,
            o.holding_period,
            o.actual_move,
            o.expiry_result,
            o.resolved_as,
            o.raw_payload AS outcome_raw_payload,
            p.ticker,
            p.direction,
            p.timestamp,
            p.raw_payload AS prediction_raw_payload,
            p.signal_stack
        FROM outcomes o
        JOIN predictions p ON p.prediction_id = o.prediction_id
        WHERE o.expiry_result IN (?, ?)
        ORDER BY p.timestamp ASC, o.prediction_id ASC
        """,
        PRICE_EXPIRY_RESULTS,
    ).fetchall()

    audited: list[dict[str, Any]] = []
    for row in rows:
        outcome_raw = _parse_json_field(row['outcome_raw_payload'])
        prediction_raw = _parse_json_field(row['prediction_raw_payload'])
        signal_stack = _parse_json_field(row['signal_stack'])

        prices = extract_prices(outcome_raw, prediction_raw, signal_stack)
        actual_move = _to_float(row['actual_move'])
        if actual_move is None and prices['entry_price'] is not None and prices['latest_price'] is not None:
            actual_move = pct_move(prices['entry_price'], prices['latest_price'])

        record: dict[str, Any] = {
            'prediction_id': row['prediction_id'],
            'holding_period': row['holding_period'],
            'ticker': row['ticker'],
            'direction': row['direction'],
            'entry_price': prices['entry_price'],
            'target_price': prices['target_price'],
            'stop_loss': prices['stop_loss'],
            'latest_price': prices['latest_price'],
            'actual_move': actual_move,
            'expiry_result': row['expiry_result'],
            'resolved_as': row['resolved_as'],
            'timestamp': row['timestamp'],
        }
        record['anomalies'] = detect_price_outcome_anomalies(record)
        audited.append(record)

    return audited
