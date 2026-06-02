"""
Extract active_predictions candidates from runtime snapshot payloads.

Shared by capture script and mapping tests — read-only extraction only.
"""

from __future__ import annotations

from typing import Any

SOURCE_HINT = 'runtime_snapshot_active_predictions'

SNAPSHOT_TIMESTAMP_KEYS = ('snapshot_published_at', 'generated_at', 'published_at')
ITEM_TIMESTAMP_KEYS = ('created_at', 'timestamp', 'generated_at', 'prediction_date', 'date')
TICKER_KEYS = ('ticker', 'symbol', 'stock', 'stock_symbol', 'nse_symbol')


def extract_snapshot_published_at(snapshot: dict | None) -> str | None:
    """Return snapshot-level publish/generation timestamp if present."""
    if not isinstance(snapshot, dict):
        return None
    for key in SNAPSHOT_TIMESTAMP_KEYS:
        value = snapshot.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def extract_ticker(item: Any) -> str | None:
    """Extract ticker/symbol from a prediction-like dict."""
    if not isinstance(item, dict):
        return None
    for key in TICKER_KEYS:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip().upper()
        if text:
            return text
    return None


def _as_prediction_list(value: Any) -> list | None:
    if not isinstance(value, list) or not value:
        return None
    return value


def _active_predictions_list(container: Any) -> list | None:
    if not isinstance(container, dict):
        return None
    return _as_prediction_list(container.get('predictions'))


def _file_list(value: Any) -> list | None:
    if isinstance(value, list) and value:
        return value
    if isinstance(value, dict):
        symbols = value.get('symbols')
        if isinstance(symbols, list) and symbols:
            return symbols
    return None


def extract_runtime_snapshot_predictions(
    snapshot: dict | None,
    *,
    file_snapshot: dict | None = None,
) -> tuple[list[Any], str | None]:
    """
    Return (candidates, source_label) using first matching priority only.

    Priority:
      A. snapshot.exports.active_predictions.predictions
      B. snapshot.data.active_predictions.predictions
      C. snapshot.active_predictions.predictions
      D. file_snapshot.canonical_opportunity_feed (if list)
      E. file_snapshot.top_opportunities (if list)
    """
    if isinstance(snapshot, dict):
        exports = snapshot.get('exports')
        if isinstance(exports, dict):
            preds = _active_predictions_list(exports.get('active_predictions'))
            if preds is not None:
                return preds, 'exports.active_predictions.predictions'

        data = snapshot.get('data')
        if isinstance(data, dict):
            preds = _active_predictions_list(data.get('active_predictions'))
            if preds is not None:
                return preds, 'data.active_predictions.predictions'

        preds = _active_predictions_list(snapshot.get('active_predictions'))
        if preds is not None:
            return preds, 'active_predictions.predictions'

    file_data = file_snapshot if isinstance(file_snapshot, dict) else snapshot
    if isinstance(file_data, dict):
        feed = _file_list(file_data.get('canonical_opportunity_feed'))
        if feed is not None:
            return feed, 'canonical_opportunity_feed'

        top = _file_list(file_data.get('top_opportunities'))
        if top is not None:
            return top, 'top_opportunities'

    return [], None


def apply_snapshot_timestamps(items: list[Any], snapshot_ts: str | None) -> list[dict]:
    """Fill missing item timestamps from snapshot publish time."""
    prepared: list[dict] = []
    if not isinstance(items, list):
        return prepared

    for item in items:
        if not isinstance(item, dict):
            continue
        merged = dict(item)
        has_item_ts = any(
            merged.get(key) is not None and str(merged.get(key)).strip() != ''
            for key in ITEM_TIMESTAMP_KEYS
        )
        if not has_item_ts and snapshot_ts:
            merged['timestamp'] = snapshot_ts
        elif not has_item_ts and merged.get('generated_at'):
            merged['timestamp'] = merged['generated_at']
        prepared.append(merged)
    return prepared
