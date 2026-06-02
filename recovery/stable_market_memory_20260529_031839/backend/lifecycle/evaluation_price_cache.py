"""
Cached price resolution for EOD lifecycle — no live yfinance/Angel per prediction.
Uses latest_market_data.json + stored outcome/prediction fields only.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from backend.utils.config import DATA_DIR

MARKET_SNAPSHOT_FILE = DATA_DIR / 'latest_market_data.json'


def lifecycle_cache_only() -> bool:
    import os
    return os.environ.get('LIFECYCLE_CACHE_ONLY', '').strip() in ('1', 'true', 'yes')


def _normalize_ticker(ticker: Optional[str]) -> Optional[str]:
    if not ticker:
        return None
    t = str(ticker).upper().strip()
    if t in ('UNKNOWN', 'N/A', 'NONE', ''):
        return None
    if '.' in t:
        t = t.split('.')[0]
    return t


class CachedMarketSnapshot:
    """In-memory view of latest_market_data.json for fast lookups."""

    def __init__(self, path: Path = MARKET_SNAPSHOT_FILE):
        self.path = path
        self.loaded_at: Optional[str] = None
        self.prices: Dict[str, Any] = {}
        self._ltp_index: Dict[str, float] = {}
        self._reload()

    def _reload(self):
        self._ltp_index = {}
        if not self.path.exists():
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            self.loaded_at = data.get('last_updated')
            self.prices = data.get('prices') or {}
            for key, val in self.prices.items():
                ltp = _extract_ltp(val)
                if ltp is None:
                    continue
                norm = _normalize_ticker(key)
                if norm:
                    self._ltp_index[norm] = ltp
        except Exception:
            self.prices = {}
            self._ltp_index = {}

    def get_ltp(self, ticker: Optional[str]) -> Optional[float]:
        norm = _normalize_ticker(ticker)
        if not norm:
            return None
        if norm in self._ltp_index:
            return self._ltp_index[norm]
        for key, val in self.prices.items():
            if _normalize_ticker(key) == norm:
                return _extract_ltp(val)
        return None


def _extract_ltp(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val) if val else None
    if isinstance(val, dict):
        for k in ('ltp', 'price', 'close', 'last'):
            if val.get(k) is not None:
                try:
                    p = float(val[k])
                    return p if p else None
                except (TypeError, ValueError):
                    pass
    return None


def _price_from_change(entry: Optional[float], change_pct: Optional[float]) -> Optional[float]:
    if entry is None or change_pct is None:
        return None
    try:
        return round(float(entry) * (1 + float(change_pct) / 100), 4)
    except (TypeError, ValueError):
        return None


def resolve_prices_cached(
    *,
    ticker: str,
    entry: Optional[float],
    elapsed: int,
    stored: dict,
    snapshot: CachedMarketSnapshot,
    today: date,
    pred_date: date,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], str]:
    """
    Resolve entry + horizon prices without network I/O.

    Returns: (entry, price_1d, price_3d, price_7d, source_note)
    """
    notes = []

    if not entry:
        entry = stored.get('entry_price') or stored.get('outcome_entry')
        if entry:
            notes.append('entry:db')

    price_1d = stored.get('price_1d')
    price_3d = stored.get('price_3d')
    price_7d = stored.get('price_7d')

    if price_1d is None and entry is not None and stored.get('change_1d_pct') is not None:
        price_1d = _price_from_change(entry, stored.get('change_1d_pct'))
        notes.append('1d:derived_change')

    if price_3d is None and entry is not None and stored.get('change_3d_pct') is not None:
        price_3d = _price_from_change(entry, stored.get('change_3d_pct'))

    if price_7d is None and entry is not None and stored.get('change_7d_pct') is not None:
        price_7d = _price_from_change(entry, stored.get('change_7d_pct'))

    current_ltp = snapshot.get_ltp(ticker)
    if current_ltp is not None:
        if elapsed >= 1 and price_1d is None and today > pred_date:
            price_1d = current_ltp
            notes.append('1d:snapshot_ltp')
        if elapsed >= 3 and price_3d is None:
            price_3d = current_ltp
            notes.append('3d:snapshot_ltp')
        if elapsed >= 7 and price_7d is None:
            price_7d = current_ltp
            notes.append('7d:snapshot_ltp')
    elif not notes:
        notes.append('no_snapshot_price')

    return entry, price_1d, price_3d, price_7d, ','.join(notes) if notes else 'none'


def fetch_price_for_date_cached(
    ticker: str,
    target_date: date,
    *,
    snapshot: Optional[CachedMarketSnapshot] = None,
    allow_network: bool = False,
) -> Tuple[Optional[float], Optional[str]]:
    """Cache-first price lookup. Network only when allow_network=True and not in EOD cache mode."""
    snap = snapshot or CachedMarketSnapshot()
    today = datetime.now().date()

    if target_date >= today:
        ltp = snap.get_ltp(ticker)
        if ltp is not None:
            return ltp, today.isoformat()

    if allow_network and not lifecycle_cache_only():
        from backend.analyzers.outcome_tracker import fetch_price_for_date
        return fetch_price_for_date(ticker, target_date)

    return None, None
