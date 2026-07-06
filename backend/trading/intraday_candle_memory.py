"""
Intraday candle memory — Phase 4B.15A / 4B.17.

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
STAGE = '4B.17A'
DEFAULT_CANDLE_FILE = DATA_DIR / 'intraday_candles.jsonl'
HEARTBEAT_FILE = DATA_DIR / 'candidate_heartbeat.json'


def heartbeat_file_path() -> Path:
    override = os.environ.get('CANDIDATE_HEARTBEAT_FILE', '').strip()
    return Path(override) if override else HEARTBEAT_FILE


VALID_SOURCES = frozenset({
    'scanner', 'gainers', 'radar', 'tradecards', 'tradecard', 'quote_snapshot', 'test',
    'intraday_alert', 'intraday_batch', 'heartbeat', 'patterns_board', 'pattern_pick', 'candles',
})
VALID_TIMEFRAMES = frozenset({'snapshot', '1m', '5m', 'seq'})
MIN_DERIVED_CANDLES = 5
MIN_SNAPSHOTS_FOR_PATTERNS = 2


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


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def record_candidate_symbols(symbols: list[str] | tuple[str, ...], *, source: str = 'heartbeat') -> None:
    """Track recent candidate universe for heartbeat snapshot refresh."""
    state = _load_json(heartbeat_file_path())
    recent: dict[str, str] = dict(state.get('symbols') or {})
    for sym in symbols:
        clean = _normalize_symbol(sym)
        if clean:
            recent[clean] = source
    trimmed = list(recent.items())[-40:]
    _save_json(heartbeat_file_path(), {
        'symbols': dict(trimmed),
        'updated_at': _now_ist().replace(microsecond=0).isoformat(),
    })


def get_recent_candidate_symbols(*, limit: int = 20) -> list[str]:
    state = _load_json(heartbeat_file_path())
    symbols = list((state.get('symbols') or {}).keys())
    return symbols[-limit:]


def _scanner_row_for_symbol(sym: str) -> dict[str, Any]:
    try:
        from backend.trading.opening_rally_radar import SCANNER_FILE, _load_json, _scanner_index

        scanner = _scanner_index(_load_json(SCANNER_FILE))
        row = dict(scanner.get(sym) or {})
        if row:
            return row
    except Exception:
        pass
    return {'ticker': sym}


def refresh_candidate_snapshots(
    symbols: list[str] | None = None,
    *,
    source: str = 'heartbeat',
) -> int:
    """Refresh snapshots for recent candidate symbols using latest scanner quotes."""
    syms = symbols or get_recent_candidate_symbols()
    stored = 0
    for sym in syms:
        clean = _normalize_symbol(sym)
        if not clean:
            continue
        row = _scanner_row_for_symbol(clean)
        candidate = {'ticker': clean, **row}
        if capture_snapshot_from_candidate(candidate, source=source):
            stored += 1
    return stored


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
    from backend.trading.ohlcv_candidate_adapter import extract_candidate_ohlcv, is_usable_ohlcv_snapshot

    sym = _normalize_symbol(symbol)
    if not sym or not isinstance(row, dict):
        return None
    payload = extract_candidate_ohlcv({'ticker': sym, **row})
    if not is_usable_ohlcv_snapshot(payload):
        return None
    ist_now = _now_ist()
    payload.update({
        'created_at': ist_now.replace(microsecond=0).isoformat(),
        'session_date': _session_date(ist_now),
        'source': source if source in VALID_SOURCES else 'quote_snapshot',
        'timeframe': timeframe if timeframe in VALID_TIMEFRAMES else 'snapshot',
    })
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
    close = _safe_float(row.get('close'))
    if close is None:
        return None
    open_ = _safe_float(row.get('open'))
    high = _safe_float(row.get('high'))
    low = _safe_float(row.get('low'))
    if open_ is None or high is None or low is None:
        return None
    return {
        'timestamp': str(row.get('created_at') or row.get('session_date') or ''),
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': _safe_float(row.get('volume'), 0.0) or 0.0,
        'derived_from_snapshots': False,
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


def _derive_candles_from_snapshots(
    snapshots: list[dict[str, Any]],
    *,
    bucket_minutes: int,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for snap in snapshots:
        close = _safe_float(snap.get('close'))
        if close is None:
            continue
        key = _bucket_key(str(snap.get('created_at') or ''), bucket_minutes)
        buckets.setdefault(key, []).append(snap)

    candles: list[dict[str, Any]] = []
    for key in sorted(buckets.keys()):
        group = buckets[key]
        closes = [c for c in (_safe_float(s.get('close')) for s in group) if c is not None]
        if not closes:
            continue
        opens = [o for o in (_safe_float(s.get('open')) for s in group) if o is not None]
        highs = [h for h in (_safe_float(s.get('high')) for s in group) if h is not None]
        lows = [l for l in (_safe_float(s.get('low')) for s in group) if l is not None]
        volumes = [v for v in (_safe_float(s.get('volume')) for s in group) if v is not None]

        open_ = opens[0] if opens else closes[0]
        high = max(highs + closes)
        low = min(lows + closes)
        close = closes[-1]
        volume = volumes[-1] if volumes else 0.0
        derived = (
            len(group) > 1
            or any(str(s.get('source_quality') or '') == 'partial' for s in group)
            or not opens
            or not highs
            or not lows
        )
        candle: dict[str, Any] = {
            'timestamp': key,
            'open': open_,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        }
        if derived:
            candle['derived_from_snapshots'] = True
        candles.append(candle)
    return candles


def build_ohlcv_from_snapshots(
    symbol: str,
    *,
    timeframe: str = '5m',
    session_date: str | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    """Build OHLCV candles from stored snapshots, including partial/derived bars."""
    snapshots = load_recent_candles(symbol, session_date=session_date, limit=limit * 8)
    if not snapshots:
        return []

    tf = str(timeframe or '5m').lower()
    if tf == 'seq':
        candles: list[dict[str, Any]] = []
        for snap in snapshots:
            close = _safe_float(snap.get('close'))
            if close is None:
                continue
            candles.append({
                'timestamp': str(snap.get('created_at') or ''),
                'open': close,
                'high': close,
                'low': close,
                'close': close,
                'volume': _safe_float(snap.get('volume'), 0.0) or 0.0,
                'derived_from_snapshots': True,
            })
        return candles[-limit:]

    if tf == 'snapshot':
        candles = [c for c in (_snapshot_to_candle(s) for s in snapshots) if c]
        return candles[-limit:]

    bucket_minutes = 1 if tf == '1m' else 5
    candles = _derive_candles_from_snapshots(snapshots, bucket_minutes=bucket_minutes)
    return candles[-limit:]


def get_candle_readiness(symbol: str, *, session_date: str | None = None) -> dict[str, Any]:
    """Summarize snapshot/candle counts and pattern readiness for /candles and /patterns."""
    sym = _normalize_symbol(symbol)
    snapshots = load_recent_candles(sym, session_date=session_date, limit=500)
    derived_5m = build_ohlcv_from_snapshots(sym, timeframe='5m', session_date=session_date, limit=120)
    derived_1m = build_ohlcv_from_snapshots(sym, timeframe='1m', session_date=session_date, limit=120)
    derived_seq = build_ohlcv_from_snapshots(sym, timeframe='seq', session_date=session_date, limit=120)
    derived = derived_5m
    for candidate in (derived_1m, derived_seq):
        if len(candidate) > len(derived):
            derived = candidate
    latest = snapshots[-1] if snapshots else {}
    latest_close = _safe_float(latest.get('close'))
    latest_high = _safe_float(latest.get('high'))
    latest_low = _safe_float(latest.get('low'))

    qualities = {str(s.get('source_quality') or 'partial') for s in snapshots}
    if not snapshots:
        source_quality = 'none'
    elif qualities == {'full'}:
        source_quality = 'full'
    elif any(c.get('derived_from_snapshots') for c in derived):
        source_quality = 'derived'
    else:
        source_quality = 'partial'

    snapshot_count = len(snapshots)
    derived_count = len(derived)
    pattern_ready = snapshot_count >= MIN_SNAPSHOTS_FOR_PATTERNS and derived_count >= MIN_DERIVED_CANDLES
    reason = ''
    if snapshot_count == 0:
        reason = 'no snapshots yet'
    elif snapshot_count < MIN_SNAPSHOTS_FOR_PATTERNS:
        reason = f'need at least {MIN_SNAPSHOTS_FOR_PATTERNS} snapshots'
    elif derived_count < MIN_DERIVED_CANDLES:
        reason = f'need at least {MIN_DERIVED_CANDLES} derived candles'

    return {
        'symbol': sym,
        'snapshot_count': snapshot_count,
        'derived_count': derived_count,
        'latest_close': latest_close,
        'latest_high': latest_high,
        'latest_low': latest_low,
        'source_quality': source_quality,
        'pattern_ready': pattern_ready,
        'reason': reason,
        'derived_candles': derived,
        'snapshots': snapshots,
    }


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


def capture_snapshot_from_candidate(
    candidate: dict[str, Any] | None,
    *,
    source: str = 'radar',
) -> dict[str, Any] | None:
    """Capture snapshot from a radar/gainer/tradecard candidate row."""
    from backend.trading.ohlcv_candidate_adapter import extract_candidate_ohlcv, is_usable_ohlcv_snapshot

    if not isinstance(candidate, dict):
        return None
    payload = extract_candidate_ohlcv(candidate)
    if not is_usable_ohlcv_snapshot(payload):
        return None
    ist_now = _now_ist()
    payload.update({
        'created_at': ist_now.replace(microsecond=0).isoformat(),
        'session_date': _session_date(ist_now),
        'source': source if source in VALID_SOURCES else 'quote_snapshot',
        'timeframe': 'snapshot',
    })
    sym = payload.get('symbol') or _normalize_symbol(candidate.get('ticker'))
    return append_candle_snapshot(str(sym), payload)


def capture_candidate_snapshots(
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    source: str = 'radar',
) -> int:
    """Append snapshots for each candidate that has price data."""
    syms = [_normalize_symbol(c.get('ticker')) for c in candidates if isinstance(c, dict)]
    record_candidate_symbols([s for s in syms if s], source=source)
    stored = 0
    for candidate in candidates:
        if capture_snapshot_from_candidate(candidate, source=source):
            stored += 1
    return stored


def capture_snapshot_from_market_row(
    symbol: str,
    row: dict[str, Any] | None,
    *,
    source: str = 'scanner',
) -> dict[str, Any] | None:
    """Capture snapshot if quote fields exist; no-op when row empty."""
    if isinstance(row, dict) and row.get('scanner_row'):
        return capture_snapshot_from_candidate(row, source=source)
    snap = quote_snapshot_from_row(symbol, row, source=source, timeframe='snapshot')
    if not snap:
        return None
    return append_candle_snapshot(symbol, snap)


def capture_snapshot_from_alert_signal(ev: dict[str, Any]) -> dict[str, Any] | None:
    """Capture snapshot when an intraday alert/batch event fires."""
    signal = ev.get('signal') if isinstance(ev.get('signal'), dict) else ev
    if not isinstance(signal, dict):
        return None
    sym = _normalize_symbol(signal.get('ticker') or signal.get('symbol') or ev.get('ticker'))
    if not sym:
        return None
    record_candidate_symbols([sym], source='intraday_alert')
    return capture_snapshot_from_candidate({'ticker': sym, **signal}, source='intraday_alert')


def capture_intraday_batch_snapshots(partition: dict[str, Any]) -> int:
    """Capture snapshots for intraday batch new/changed events."""
    count = 0
    for key in ('new', 'changed'):
        for ev in partition.get(key) or []:
            if capture_snapshot_from_alert_signal(ev):
                count += 1
    return count
