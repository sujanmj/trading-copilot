"""
Market data validation — reject invalid prices before they poison AI pipeline.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from backend.utils.config import DATA_DIR

MAX_ABS_CHANGE_PCT = float(__import__('os').environ.get('MARKET_MAX_CHANGE_PCT', '22.0'))
MIN_VALID_PRICE = float(__import__('os').environ.get('MARKET_MIN_PRICE', '0.05'))
MAX_VALID_PRICE = float(__import__('os').environ.get('MARKET_MAX_PRICE', '500000'))
MAX_STALE_HOURS = float(__import__('os').environ.get('MARKET_MAX_STALE_HOURS', '18'))


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def validate_price_row(
    row: dict,
    *,
    symbol_name: str = '',
    previous_row: Optional[dict] = None,
) -> Tuple[bool, str, Optional[dict]]:
    """
    Validate a single price row.
    Returns (ok, reason, cleaned_row).
    """
    if not isinstance(row, dict):
        return False, 'not_dict', None

    price = _safe_float(row.get('price'))
    change_pct = _safe_float(row.get('change_percent'))

    if price is None:
        _log('INVALID MARKET DATA', f'{symbol_name}: null/NaN price')
        return False, 'nan_price', None

    if price <= 0:
        _log('INVALID MARKET DATA', f'{symbol_name}: non-positive price {price}')
        return False, 'non_positive', None

    if price < MIN_VALID_PRICE or price > MAX_VALID_PRICE:
        _log('INVALID MARKET DATA', f'{symbol_name}: price out of range {price}')
        return False, 'out_of_range', None

    if change_pct is not None and abs(change_pct) > MAX_ABS_CHANGE_PCT:
        _log('INVALID MARKET DATA', f'{symbol_name}: absurd change {change_pct:+.2f}%')
        return False, 'absurd_change', None

    prev_price = _safe_float((previous_row or {}).get('price'))
    if prev_price and prev_price > 0:
        implied = abs((price - prev_price) / prev_price * 100)
        if implied > MAX_ABS_CHANGE_PCT and (change_pct is None or abs(change_pct) > MAX_ABS_CHANGE_PCT):
            _log('INVALID MARKET DATA', f'{symbol_name}: spike vs previous {implied:.1f}%')
            return False, 'spike_vs_previous', None

    cleaned = {
        'price': round(price, 2),
        'change_percent': round(change_pct, 2) if change_pct is not None else 0.0,
        'source': str(row.get('source') or 'unknown'),
        'validated_at': datetime.now().isoformat(),
    }
    if row.get('stale'):
        cleaned['stale'] = True
    if row.get('preserved'):
        cleaned['preserved'] = True
    return True, '', cleaned


def preserve_previous_row(previous_row: dict, reason: str) -> dict:
    """Keep last valid snapshot when fresh fetch fails validation."""
    preserved = dict(previous_row)
    preserved['preserved'] = True
    preserved['stale'] = True
    preserved['preserve_reason'] = reason
    preserved['source'] = f"preserved:{previous_row.get('source', 'unknown')}"
    _log('STALE MARKET DATA', f"Preserved previous valid price ({reason})")
    return preserved


def validate_market_snapshot(
    snapshot: dict,
    *,
    previous_snapshot: Optional[dict] = None,
    file_label: str = 'market',
) -> Tuple[dict, dict]:
    """
    Validate full market JSON snapshot.
    Returns (cleaned_snapshot, validation_meta).
    """
    prev_prices = (previous_snapshot or {}).get('prices') or {}
    prices_in = (snapshot or {}).get('prices') or {}
    cleaned_prices = {}
    meta = {
        'validated': 0,
        'rejected': 0,
        'preserved_previous': 0,
        'degraded': False,
        'reject_reasons': [],
    }

    for name, row in prices_in.items():
        prev_row = prev_prices.get(name)
        ok, reason, cleaned = validate_price_row(row, symbol_name=name, previous_row=prev_row)
        if ok and cleaned:
            cleaned_prices[name] = cleaned
            meta['validated'] += 1
            continue

        meta['rejected'] += 1
        meta['reject_reasons'].append(f'{name}:{reason}')
        if prev_row and _safe_float(prev_row.get('price')):
            cleaned_prices[name] = preserve_previous_row(prev_row, reason)
            meta['preserved_previous'] += 1
            meta['degraded'] = True
        else:
            _log('SOURCE DEGRADED', f'{file_label} {name} — no valid previous snapshot')

    if meta['rejected'] > 0:
        meta['degraded'] = True
        _log('SOURCE DEGRADED', f'{file_label}: {meta["rejected"]} symbols rejected')

    last_updated = snapshot.get('last_updated')
    if last_updated and meta['preserved_previous'] == 0:
        try:
            ts = datetime.fromisoformat(str(last_updated).replace('Z', '+00:00'))
            age_h = (datetime.now(ts.tzinfo) - ts).total_seconds() / 3600 if ts.tzinfo else (
                datetime.now() - ts.replace(tzinfo=None)
            ).total_seconds() / 3600
            if age_h > MAX_STALE_HOURS:
                _log('STALE MARKET DATA', f'{file_label} snapshot age {age_h:.1f}h')
                meta['stale_snapshot'] = True
                meta['degraded'] = True
        except Exception:
            pass

    out = dict(snapshot or {})
    out['prices'] = cleaned_prices
    out['symbols_ok'] = len(cleaned_prices)
    out['symbols_failed'] = max(0, int(snapshot.get('total_symbols', 0)) - len(cleaned_prices))
    out['validation'] = meta
    return out, meta


def sanitize_for_analyzer(india_markets: Optional[dict]) -> Optional[dict]:
    """Light validation at analyzer ingest — strip invalid rows."""
    if not isinstance(india_markets, dict):
        return india_markets
    prices = india_markets.get('prices') or {}
    clean = {}
    for name, row in prices.items():
        ok, _, cleaned = validate_price_row(row, symbol_name=name)
        if ok and cleaned:
            clean[name] = cleaned
    if len(clean) == len(prices):
        return india_markets
    out = dict(india_markets)
    out['prices'] = clean
    out['analyzer_sanitized'] = True
    _log('INVALID MARKET DATA', f'analyzer stripped {len(prices) - len(clean)} invalid rows')
    return out


def load_previous_snapshot(path=None) -> dict:
    from pathlib import Path
    path = path or (DATA_DIR / 'latest_market_data.json')
    path = Path(path)
    if not path.exists():
        return {}
    try:
        import json
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
