"""
Intraday candle memory — Phase 4B.15A.

Lightweight JSONL store of OHLCV snapshots for chart pattern detection.
Paper/research only — no LLM calls.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.15A'
DEFAULT_CANDLE_FILE = DATA_DIR / 'intraday_candles.jsonl'
VALID_SOURCES = frozenset({'scanner', 'gainers', 'radar', 'quote_snapshot', 'test'})
VALID_TIMEFRAMES = frozenset({'snapshot', '1m', '5m'})


def candle_file_path() -> Path:
    override = os.environ.get('INTRADAY_CANDLES_FILE', '').strip()
    return Path(override) if override else DEFAULT_CANDLE_FILE


def _now_ist() -> datetime:
    return datetime.now(tz=IST)


def _session_date(dt: datetime | None = None) -> str:
    return (dt or _now_ist()).strftime('%Y-%m-%d')


def _normalize_symbol(value: object) -> str:
    return re.sub(r'[^A-Z0-9&-]', '', str(value or '').strip().upper())


def _safe_float(value: object, default: float | None = None) -> float | None:
    if value in (None, '', '—', '-', 'NA', 'N/A'):
        return default
    try:
        text = str(value).strip().replace(',', '')
        if not text:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')


def _load_jsonl(path: Path, limit: int = 100000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open('r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows[-limit:]


def quote_snapshot_from_row(
    symbol: str,
    row: dict[str, Any] | None,
    *,
    source: str = 'scanner',
    timeframe: str = 'snapshot',
) -> dict[str, Any] | None:
    """Build a candle snapshot from scanner/gainer/quote row without faking OHLC."""
    sym = _normalize_symbol(symbol)
    if not sym or not isinstance(row, dict):
        return None
    close = _safe_float(row.get('price') or row.get('close') or row.get('last_price'))
    if close is None:
        return None
    open_ = _safe_float(row.get('open') or row.get('open_price'))
    high = _safe_float(row.get('high') or row.get('day_high'))
    low = _safe_float(row.get('low') or row.get('day_low'))
    volume = _safe_float(row.get('volume') or row.get('traded_volume'))
    vwap = _safe_float(row.get('vwap'))
    partial = open_ is None or high is None or low is None
    ist_now = _now_ist()
    payload: dict[str, Any] = {
        'created_at': ist_now.replace(microsecond=0).isoformat(),
        'session_date': _session_date(ist_now),
        'symbol': sym,
        'close': close,
        'source': source if source in VALID_SOURCES else 'quote_snapshot',
        'timeframe': timeframe if timeframe in VALID_TIMEFRAMES else 'snapshot',
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


def append_candle_snapshot(symbol: str, data: dict[str, Any]) -> dict[str, Any]:
    """Append one candle snapshot record to intraday memory."""
    sym = _normalize_symbol(symbol or data.get('symbol'))
    if not sym:
        raise ValueError('symbol required')
    record = dict(data)
    record['symbol'] = sym
    record.setdefault('created_at', _now_ist().replace(microsecond=0).isoformat())
    record.setdefault('session_date', _session_date())
    record.setdefault('timeframe', 'snapshot')
    record.setdefault('source', 'quote_snapshot')
    if 'close' not in record and record.get('price') is not None:
        record['close'] = record.pop('price')
    if record.get('close') in (None, ''):
        raise ValueError('close required')
    if 'source_quality' not in record:
        partial = any(record.get(k) in (None, '') for k in ('open', 'high', 'low'))
        record['source_quality'] = 'partial' if partial else 'full'
    _append_jsonl(candle_file_path(), record)
    return record


def load_recent_candles(
    symbol: str,
    *,
    session_date: str | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    """Load recent snapshots for one symbol, newest last."""
    sym = _normalize_symbol(symbol)
    if not sym:
        return []
    rows = _load_jsonl(candle_file_path(), limit=100000)
    filtered = [r for r in rows if _normalize_symbol(r.get('symbol')) == sym]
    if session_date:
        filtered = [r for r in filtered if str(r.get('session_date') or '') == session_date]
    filtered.sort(key=lambda r: str(r.get('created_at') or ''))
    return filtered[-limit:]


def _snapshot_to_candle(row: dict[str, Any]) -> dict[str, Any] | None:
    if str(row.get('source_quality') or '') == 'partial':
        return None
    close = _safe_float(row.get('close'))
    high = _safe_float(row.get('high'))
    low = _safe_float(row.get('low'))
    open_ = _safe_float(row.get('open'))
    if close is None or high is None or low is None or open_ is None:
        return None
    return {
        'timestamp': str(row.get('created_at') or row.get('session_date') or ''),
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': _safe_float(row.get('volume'), 0.0) or 0.0,
    }


def _bucket_key(created_at: str, minutes: int) -> str:
    try:
        dt = datetime.fromisoformat(str(created_at))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        dt = dt.astimezone(IST)
        floored = dt.replace(minute=(dt.minute // minutes) * minutes, second=0, microsecond=0)
        return floored.isoformat()
    except ValueError:
        return str(created_at)


def build_ohlcv_from_snapshots(
    symbol: str,
    *,
    timeframe: str = '5m',
    session_date: str | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    """Build OHLCV candle list from stored snapshots."""
    snapshots = load_recent_candles(symbol, session_date=session_date, limit=limit * 4)
    full = [s for s in snapshots if str(s.get('source_quality') or '') != 'partial']
    if not full:
        return []

    tf = str(timeframe or '5m').lower()
    if tf == 'snapshot':
        candles = [c for c in (_snapshot_to_candle(s) for s in full) if c]
        return candles[-limit:]

    bucket_minutes = 1 if tf == '1m' else 5
    buckets: dict[str, list[dict[str, Any]]] = {}
    for snap in full:
        key = _bucket_key(str(snap.get('created_at') or ''), bucket_minutes)
        buckets.setdefault(key, []).append(snap)

    candles: list[dict[str, Any]] = []
    for key in sorted(buckets.keys()):
        group = buckets[key]
        opens = [_safe_float(s.get('open')) for s in group]
        highs = [_safe_float(s.get('high')) for s in group]
        lows = [_safe_float(s.get('low')) for s in group]
        closes = [_safe_float(s.get('close')) for s in group]
        volumes = [_safe_float(s.get('volume'), 0.0) or 0.0 for s in group]
        if not all(opens) or not all(highs) or not all(lows) or not all(closes):
            continue
        candles.append({
            'timestamp': key,
            'open': opens[0],
            'high': max(h for h in highs if h is not None),
            'low': min(l for l in lows if l is not None),
            'close': closes[-1],
            'volume': sum(volumes),
        })
    return candles[-limit:]


def clear_old_candles(*, max_days: int = 5) -> int:
    """Remove snapshots older than max_days. Returns rows removed."""
    path = candle_file_path()
    if not path.exists():
        return 0
    cutoff = (_now_ist() - timedelta(days=max(1, int(max_days)))).date()
    kept: list[dict[str, Any]] = []
    removed = 0
    for row in _load_jsonl(path, limit=500000):
        session = str(row.get('session_date') or '')
        try:
            row_date = datetime.strptime(session, '%Y-%m-%d').date()
        except ValueError:
            kept.append(row)
            continue
        if row_date >= cutoff:
            kept.append(row)
        else:
            removed += 1
    if removed:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8') as handle:
            for row in kept:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    return removed


def capture_snapshot_from_market_row(
    symbol: str,
    row: dict[str, Any] | None,
    *,
    source: str = 'scanner',
) -> dict[str, Any] | None:
    """Capture snapshot if quote fields exist; no-op when row empty."""
    snap = quote_snapshot_from_row(symbol, row, source=source, timeframe='snapshot')
    if not snap:
        return None
    return append_candle_snapshot(symbol, snap)
