"""
OHLCV adapter for radar / gainers / tradecard candidates — Phase 4B.17.

Maps live candidate rows to candle snapshots without faking missing OHLC fields.
"""

from __future__ import annotations

import re
from typing import Any

STAGE = '4B.17'

_PRICE_KEYS = ('close', 'price', 'last_price', 'ltp', 'current_price')
_OPEN_KEYS = ('open', 'open_price')
_HIGH_KEYS = ('high', 'day_high')
_LOW_KEYS = ('low', 'day_low')
_VOLUME_KEYS = ('volume', 'traded_volume')


def _normalize_symbol(value: object) -> str:
    return re.sub(r'[^A-Z0-9&-]', '', str(value or '').strip().upper())


def _safe_float(value: object) -> float | None:
    if value in (None, '', '—', '-', 'NA', 'N/A'):
        return None
    try:
        text = str(value).strip().replace(',', '')
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _first_float(raw: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        val = _safe_float(raw.get(key))
        if val is not None:
            return val
    return None


def _merged_candidate_sources(candidate: dict[str, Any]) -> dict[str, Any]:
    merged = dict(candidate)
    nested = candidate.get('scanner_row')
    if isinstance(nested, dict):
        for key, value in nested.items():
            if key not in merged or merged.get(key) in (None, ''):
                merged[key] = value
    return merged


def extract_candidate_symbol(candidate: object) -> str:
    if not isinstance(candidate, dict):
        return ''
    for key in ('ticker', 'symbol'):
        sym = _normalize_symbol(candidate.get(key))
        if sym:
            return sym
    return ''


def normalize_ohlcv_snapshot(symbol: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw quote fields into a candle snapshot payload."""
    sym = _normalize_symbol(symbol) or extract_candidate_symbol(raw)
    close = _first_float(raw, _PRICE_KEYS)
    open_ = _first_float(raw, _OPEN_KEYS)
    high = _first_float(raw, _HIGH_KEYS)
    low = _first_float(raw, _LOW_KEYS)
    volume = _first_float(raw, _VOLUME_KEYS)
    vwap = _safe_float(raw.get('vwap'))

    partial = open_ is None or high is None or low is None
    payload: dict[str, Any] = {
        'symbol': sym,
        'close': close,
        'source_quality': 'partial' if partial else 'full',
    }
    if open_ is not None:
        payload['open'] = open_
    if high is not None:
        payload['high'] = high
    if low is not None:
        payload['low'] = low
    if volume is not None:
        payload['volume'] = volume
    if vwap is not None:
        payload['vwap'] = vwap
    return payload


def extract_candidate_ohlcv(candidate: object) -> dict[str, Any] | None:
    """Extract OHLCV snapshot fields from a radar/gainer/tradecard candidate row."""
    if not isinstance(candidate, dict):
        return None
    sym = extract_candidate_symbol(candidate)
    if not sym:
        return None
    raw = _merged_candidate_sources(candidate)
    snapshot = normalize_ohlcv_snapshot(sym, raw)
    if snapshot.get('close') in (None, ''):
        return None
    return snapshot


def is_usable_ohlcv_snapshot(snapshot: dict[str, Any] | None) -> bool:
    """True when snapshot has at least a close price."""
    if not isinstance(snapshot, dict):
        return False
    return _safe_float(snapshot.get('close')) is not None
