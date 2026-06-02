"""
Live capture of predictions/opportunities into canonical_market_memory.db.

Additive and non-fatal — all public entry points swallow errors.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

from backend.utils.config import ENABLE_MARKET_MEMORY_CAPTURE

TICKER_KEYS = ('ticker', 'symbol', 'stock', 'stock_symbol')
TIMESTAMP_KEYS = ('created_at', 'timestamp', 'prediction_date', 'date')
SOURCE_KEYS = ('source', 'run_type', 'use_case', 'origin')
DIRECTION_KEYS = ('recommendation', 'direction', 'action', 'signal', 'prediction')
SECTOR_KEYS = ('sector', 'industry')
REASONING_KEYS = ('reasoning', 'rationale', 'explanation', 'ai_reasoning', 'notes', 'logic')

BULLISH_TOKENS = frozenset(
    {'BUY', 'STRONG_BUY', 'ACCUMULATE', 'LONG', 'BULLISH', 'UP', 'POSITIVE'}
)
BEARISH_TOKENS = frozenset(
    {'SELL', 'STRONG_SELL', 'AVOID', 'SHORT', 'BEARISH', 'DOWN', 'NEGATIVE'}
)
NEUTRAL_TOKENS = frozenset({'HOLD', 'WATCH', 'NEUTRAL', 'WAIT', 'SIDEWAYS'})

CONFIDENCE_TEXT_MAP = {
    'HIGH': 0.8,
    'STRONG': 0.8,
    'MEDIUM': 0.55,
    'MODERATE': 0.55,
    'LOW': 0.3,
    'WEAK': 0.3,
}

SIGNAL_STACK_FIELDS = (
    'cross_validation',
    'signal_type',
    'prediction_horizon',
    'category',
    'recommendation',
    'target_price',
    'stop_loss',
    'current_price',
    'confidence',
    'entry_price',
    'rank_in_list',
    'overall_conviction',
    'elite_verified',
    'display_confidence',
)


def _log_error(message: str) -> None:
    print(f'[MARKET_MEMORY_CAPTURE] {message}', file=sys.stderr)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_get(item: dict, *names: str, default: Any = None) -> Any:
    for name in names:
        if name in item and item[name] is not None:
            return item[name]
    return default


def _parse_json_maybe(value: Any) -> dict | list | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
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
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def _normalize_direction(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip().upper().replace(' ', '_').replace('-', '_')
    if not token:
        return None
    if token in BULLISH_TOKENS:
        return 'BULLISH'
    if token in BEARISH_TOKENS:
        return 'BEARISH'
    if token in NEUTRAL_TOKENS:
        return 'NEUTRAL'
    for bullish in BULLISH_TOKENS:
        if bullish in token:
            return 'BULLISH'
    for bearish in BEARISH_TOKENS:
        if bearish in token:
            return 'BEARISH'
    for neutral in NEUTRAL_TOKENS:
        if neutral in token:
            return 'NEUTRAL'
    return token


def _normalize_confidence(value: Any) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, (int, float)):
        try:
            return float(value), None
        except (TypeError, ValueError):
            return None, None
    text = str(value).strip()
    if not text:
        return None, None
    try:
        return float(text), text
    except ValueError:
        pass
    label = text.upper()
    for key, score in CONFIDENCE_TEXT_MAP.items():
        if key in label:
            return score, text
    return None, text


def _build_signal_stack(row_dict: dict) -> dict:
    stack: dict[str, Any] = {}
    raw = _parse_json_maybe(_safe_get(row_dict, 'raw_data', 'raw_payload'))
    raw_dict = raw if isinstance(raw, dict) else {}

    for field in SIGNAL_STACK_FIELDS:
        val = _safe_get(row_dict, field)
        if val is None and raw_dict:
            val = raw_dict.get(field)
        if val is not None:
            stack[field] = val
    return stack


def _resolve_legacy_prediction_id(item: dict) -> int | None:
    for key in ('legacy_prediction_id', 'id'):
        val = item.get(key)
        if val is not None and str(val).strip().isdigit():
            return int(str(val).strip())

    prediction_id = item.get('prediction_id')
    if prediction_id is not None:
        text = str(prediction_id).strip()
        if text.isdigit():
            return int(text)
        if text.startswith('legacy:'):
            suffix = text.split(':', 1)[1].strip()
            if suffix.isdigit():
                return int(suffix)
    return None


def _normalize_timestamp(value: Any) -> str:
    if value is None or str(value).strip() == '':
        return _now_iso()
    text = str(value).strip()
    if len(text) == 10 and text[4] == '-' and text[7] == '-':
        return f'{text}T00:00:00+00:00'
    return text


def normalize_prediction_payload(
    item: dict,
    source_hint: str | None = None,
) -> dict | None:
    """Map arbitrary prediction/opportunity dict into canonical upsert payload."""
    if not isinstance(item, dict):
        return None

    ticker = _safe_get(item, *TICKER_KEYS)
    if not ticker or not str(ticker).strip():
        return None

    timestamp = _normalize_timestamp(_safe_get(item, *TIMESTAMP_KEYS))
    source = source_hint or _safe_get(item, *SOURCE_KEYS) or 'internal_ai'
    direction = _normalize_direction(_safe_get(item, *DIRECTION_KEYS))

    confidence_val, confidence_label = _normalize_confidence(
        _safe_get(item, 'confidence', 'display_confidence')
    )
    raw_data = _parse_json_maybe(_safe_get(item, 'raw_data', 'raw_payload'))
    market_regime = _safe_get(item, 'market_regime', 'regime')
    if market_regime is None and isinstance(raw_data, dict):
        market_regime = raw_data.get('market_regime') or raw_data.get('regime')

    payload: dict[str, Any] = {
        'ticker': str(ticker).strip().upper(),
        'timestamp': timestamp,
        'source': str(source),
        'direction': direction,
        'confidence': confidence_val,
        'confidence_label': confidence_label,
        'market_regime': market_regime,
        'sector': _safe_get(item, *SECTOR_KEYS),
        'reasoning': _safe_get(item, *REASONING_KEYS),
        'signal_stack': _build_signal_stack(item),
        'raw_payload': item,
    }

    legacy_id = _resolve_legacy_prediction_id(item)
    if legacy_id is not None:
        payload['legacy_prediction_id'] = legacy_id

    return payload


def capture_prediction(payload: dict, source_hint: str | None = None) -> str | None:
    """Capture one prediction into canonical market memory."""
    if not ENABLE_MARKET_MEMORY_CAPTURE:
        return None
    try:
        from backend.storage.market_memory_db import upsert_prediction

        normalized = normalize_prediction_payload(payload, source_hint=source_hint)
        if normalized is None:
            return None
        return upsert_prediction(normalized)
    except Exception as exc:
        _log_error(f'capture_prediction failed: {exc}')
        return None


def capture_predictions(
    items: list,
    source_hint: str | None = None,
) -> dict:
    """Capture a batch of predictions; returns summary counts."""
    summary = {'attempted': 0, 'captured': 0, 'skipped': 0, 'prediction_ids': []}
    if not ENABLE_MARKET_MEMORY_CAPTURE:
        return summary
    if not isinstance(items, list):
        return summary

    for item in items:
        summary['attempted'] += 1
        try:
            prediction_id = capture_prediction(item, source_hint=source_hint)
            if prediction_id:
                summary['captured'] += 1
                summary['prediction_ids'].append(prediction_id)
            else:
                summary['skipped'] += 1
        except Exception as exc:
            summary['skipped'] += 1
            _log_error(f'capture_predictions item failed: {exc}')
    return summary


def capture_opportunity_as_prediction(
    item: dict,
    source_hint: str = 'opportunity_engine',
) -> str | None:
    """Capture ranked opportunity dict as a canonical prediction row."""
    if not isinstance(item, dict):
        return None
    merged = dict(item)
    if 'symbol' in merged and 'ticker' not in merged:
        merged['ticker'] = merged['symbol']
    if 'action' in merged and 'recommendation' not in merged:
        merged['recommendation'] = merged['action']
    return capture_prediction(merged, source_hint=source_hint)
