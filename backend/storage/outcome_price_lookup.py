"""
Safe local price lookup for outcome resolver — Stage 49C.

Reads only real stored prices from scanner, market data, reports, snapshots, and OHLC cache.
Never invents prices.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.storage.market_memory_outcomes import (
    _parse_signal_stack,
    _parse_timestamp,
    _to_float,
    load_latest_market_data,
    parse_prediction_raw_payload,
)
from backend.utils.config import DATA_DIR

REFERENCE_WINDOW_BEFORE_HOURS = 48.0
REFERENCE_WINDOW_AFTER_HOURS = 6.0

PRICE_FIELD_KEYS = (
    'reference_price',
    'entry_price',
    'current_price',
    'price',
    'close',
    'ltp',
    'last_price',
    'previous_close',
)

MARKET_DATA_FILES = (
    ('latest_market_data_memory_enriched', DATA_DIR / 'latest_market_data_memory_enriched.json'),
    ('latest_market_data', DATA_DIR / 'latest_market_data.json'),
)

REPORT_FILES = (
    ('final_confidence_report', DATA_DIR / 'final_confidence_report.json'),
    ('daily_report_pack', DATA_DIR / 'daily_report_pack_latest.json'),
)


@dataclass(frozen=True)
class PriceHit:
    price: float
    source: str
    timestamp: datetime | None = None


def _load_json(path: Path) -> dict | None:
    try:
        if not path.is_file():
            return None
        parsed = json.loads(path.read_text(encoding='utf-8'))
        return parsed if isinstance(parsed, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _extract_price_from_mapping(data: dict | None) -> float | None:
    if not isinstance(data, dict):
        return None
    for key in PRICE_FIELD_KEYS:
        val = _to_float(data.get(key))
        if val is not None and val > 0:
            return val
    return None


def _timestamp_in_reference_window(source_ts: datetime | None, signal_time: datetime | None) -> bool:
    if signal_time is None:
        return False
    if source_ts is None:
        return False
    before_h = (signal_time - source_ts).total_seconds() / 3600.0
    after_h = (source_ts - signal_time).total_seconds() / 3600.0
    return before_h <= REFERENCE_WINDOW_BEFORE_HOURS and after_h <= REFERENCE_WINDOW_AFTER_HOURS


def _timestamp_after_horizon(source_ts: datetime | None, signal_time: datetime | None, min_hours: float) -> bool:
    if signal_time is None or source_ts is None:
        return False
    age_h = (source_ts - signal_time).total_seconds() / 3600.0
    return age_h >= float(min_hours)


def _market_entry_timestamp(data: dict, entry: dict) -> datetime | None:
    """Reference lookup may use per-entry or file-level timestamps."""
    entry_ts = _evaluation_entry_timestamp(entry if isinstance(entry, dict) else None)
    if entry_ts is not None:
        return entry_ts
    for key in ('last_updated', 'generated_at', 'timestamp'):
        parsed = _parse_timestamp(data.get(key))
        if parsed is not None:
            return parsed
    return None


def _evaluation_entry_timestamp(entry: dict | None) -> datetime | None:
    """Evaluation requires a real per-entry timestamp — no file-level fallback."""
    if not isinstance(entry, dict):
        return None
    for key in ('validated_at', 'timestamp', 'as_of'):
        parsed = _parse_timestamp(entry.get(key))
        if parsed is not None:
            return parsed
    return None


EVALUATION_FORBIDDEN_SOURCES = frozenset({
    'prediction_payload',
    'report_payload',
})


def validate_resolution_price_pair(
    ref_hit: PriceHit,
    eval_hit: PriceHit,
    signal_time: datetime,
    horizon_hours: float,
) -> bool:
    """
    Hard safety gate — both prices must be real, distinct-in-time, and eval must be post-horizon.
    Never allows reference price/time to serve as evaluation.
    """
    if ref_hit.price <= 0 or eval_hit.price <= 0:
        return False
    if eval_hit.timestamp is None:
        return False
    if eval_hit.source in EVALUATION_FORBIDDEN_SOURCES:
        return False
    if eval_hit.timestamp <= signal_time:
        return False
    if not _timestamp_after_horizon(eval_hit.timestamp, signal_time, horizon_hours):
        return False
    if ref_hit.timestamp is not None:
        if eval_hit.timestamp <= ref_hit.timestamp:
            return False
        if eval_hit.timestamp == ref_hit.timestamp:
            return False
    if abs(eval_hit.price - ref_hit.price) < 1e-9:
        anchor = ref_hit.timestamp or signal_time
        if not _timestamp_after_horizon(eval_hit.timestamp, anchor, horizon_hours):
            return False
    return True


def _iter_report_rows(report: dict) -> list[dict]:
    rows: list[dict] = []
    for key in ('top_candidates', 'rows', 'candidates'):
        block = report.get(key)
        if isinstance(block, list):
            rows.extend(item for item in block if isinstance(item, dict))
    pack_fc = report.get('final_confidence')
    if isinstance(pack_fc, dict):
        for key in ('top_candidates', 'rows'):
            block = pack_fc.get(key)
            if isinstance(block, list):
                rows.extend(item for item in block if isinstance(item, dict))
    tw = report.get('tomorrow_watchlist')
    if isinstance(tw, dict):
        for key in ('top_watchlist', 'watchlist', 'avoid'):
            block = tw.get(key)
            if isinstance(block, list):
                rows.extend(item for item in block if isinstance(item, dict))
    return rows


def _iter_context_ticker_prices(raw_payload: Any) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    if isinstance(raw_payload, str) and raw_payload.strip():
        try:
            raw_payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            return found
    if not isinstance(raw_payload, dict):
        return found

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            ticker = str(node.get('ticker') or node.get('symbol') or '').strip().upper()
            price = _extract_price_from_mapping(node)
            if ticker and price is not None:
                found.append((ticker, price))
            for val in node.values():
                _walk(val)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(raw_payload)
    return found


class OutcomePriceStore:
    """Lazy-loaded index of local/runtime price sources."""

    def __init__(self) -> None:
        self.scanner: dict | None = None
        self.market_files: dict[str, dict] = {}
        self.report_rows_by_prediction: dict[str, dict] = {}
        self.report_rows_by_ticker: dict[str, list[dict]] = {}
        self.scanner_prices: dict[str, list[tuple[datetime | None, float]]] = {}
        self.context_snapshots: list[tuple[datetime | None, dict[str, float]]] = []
        self._loaded = False

    @classmethod
    def load(cls) -> OutcomePriceStore:
        store = cls()
        store._ensure_loaded()
        return store

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self.scanner = _load_json(DATA_DIR / 'scanner_data.json')
        if isinstance(self.scanner, dict):
            scan_ts = _parse_timestamp(self.scanner.get('last_updated') or self.scanner.get('scan_time_local'))
            for key in ('top_signals', 'all_signals', 'signals'):
                block = self.scanner.get(key)
                if not isinstance(block, list):
                    continue
                for row in block:
                    if not isinstance(row, dict):
                        continue
                    ticker = str(row.get('ticker') or row.get('symbol') or '').strip().upper()
                    price = _extract_price_from_mapping(row)
                    if ticker and price is not None:
                        self.scanner_prices.setdefault(ticker, []).append((scan_ts, price))

        for name, path in MARKET_DATA_FILES:
            data = load_latest_market_data(path) if path.is_file() else None
            if isinstance(data, dict):
                self.market_files[name] = data

        for _name, path in REPORT_FILES:
            report = _load_json(path)
            if not isinstance(report, dict):
                continue
            for row in _iter_report_rows(report):
                ticker = str(row.get('ticker') or row.get('symbol') or '').strip().upper()
                if ticker:
                    self.report_rows_by_ticker.setdefault(ticker, []).append(row)
                pid = str(row.get('prediction_id') or '').strip()
                if pid:
                    self.report_rows_by_prediction[pid] = row

        self._load_context_snapshots()

    def _load_context_snapshots(self) -> None:
        try:
            from backend.storage.market_memory_db import get_connection, init_market_memory_db

            if not init_market_memory_db():
                return
            conn = get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT timestamp, raw_payload
                    FROM market_context_snapshots
                    ORDER BY timestamp DESC
                    LIMIT 120
                    """
                ).fetchall()
                for row in rows:
                    item = dict(row)
                    ts = _parse_timestamp(item.get('timestamp'))
                    prices = {
                        ticker: price
                        for ticker, price in _iter_context_ticker_prices(item.get('raw_payload'))
                    }
                    if prices:
                        self.context_snapshots.append((ts, prices))
            finally:
                conn.close()
        except Exception:
            return


def lookup_reference_price(
    prediction: dict,
    signal_time: datetime | None,
    store: OutcomePriceStore | None = None,
) -> PriceHit | None:
    """Best-effort reference price near signal_time from stored data only."""
    store = store or OutcomePriceStore.load()
    ticker = str(prediction.get('ticker') or '').strip().upper()
    if not ticker:
        return None

    raw = parse_prediction_raw_payload(prediction.get('raw_payload'))
    stack = _parse_signal_stack(prediction)
    for container in (stack, raw):
        price = _extract_price_from_mapping(container)
        if price is not None:
            return PriceHit(price, 'prediction_payload', signal_time)

    pid = str(prediction.get('prediction_id') or '').strip()
    if pid and pid in store.report_rows_by_prediction:
        price = _extract_price_from_mapping(store.report_rows_by_prediction[pid])
        if price is not None:
            return PriceHit(price, 'report_payload', signal_time)

    for row in store.report_rows_by_ticker.get(ticker, []):
        price = _extract_price_from_mapping(row)
        if price is not None:
            return PriceHit(price, 'report_payload', signal_time)

    for ts, price in store.scanner_prices.get(ticker, []):
        if _timestamp_in_reference_window(ts, signal_time):
            return PriceHit(price, 'scanner_data', ts)

    for source_name, data in store.market_files.items():
        entry = _market_price_entry(data, ticker)
        if entry is None:
            continue
        price, entry_obj = entry
        ts = _market_entry_timestamp(data, entry_obj if isinstance(entry_obj, dict) else {})
        if _timestamp_in_reference_window(ts, signal_time):
            return PriceHit(price, source_name, ts)

    for ts, prices in store.context_snapshots:
        price = prices.get(ticker)
        if price is not None and _timestamp_in_reference_window(ts, signal_time):
            return PriceHit(price, 'market_context_snapshot', ts)

    prev_close = _historical_close_on_or_before(ticker, signal_time)
    if prev_close is not None:
        price, day = prev_close
        day_ts = _parse_timestamp(f'{day}T00:00:00+00:00')
        return PriceHit(price, 'historical_previous_close', day_ts)

    return None


def lookup_evaluation_price(
    prediction: dict,
    signal_time: datetime | None,
    horizon: str,
    *,
    store: OutcomePriceStore | None = None,
    min_hours: float | None = None,
    now: datetime | None = None,
) -> PriceHit | None:
    """Valid close/last price after signal horizon from stored data with real timestamps only."""
    store = store or OutcomePriceStore.load()
    now = now or datetime.now(timezone.utc)
    ticker = str(prediction.get('ticker') or '').strip().upper()
    if not ticker or signal_time is None:
        return None

    from backend.storage.outcome_resolver import HORIZON_MIN_HOURS

    horizon_hours = float(min_hours if min_hours is not None else HORIZON_MIN_HOURS.get(horizon, HORIZON_MIN_HOURS['UNKNOWN']))

    candidates: list[PriceHit] = []

    for source_name, data in store.market_files.items():
        entry = _market_price_entry(data, ticker)
        if entry is None:
            continue
        price, entry_obj = entry
        if not isinstance(entry_obj, dict):
            continue
        ts = _evaluation_entry_timestamp(entry_obj)
        if ts is None or ts <= signal_time:
            continue
        if not _timestamp_after_horizon(ts, signal_time, horizon_hours):
            continue
        if ts > now:
            continue
        candidates.append(PriceHit(price, source_name, ts))

    for ts, price in store.scanner_prices.get(ticker, []):
        if ts is None or ts <= signal_time:
            continue
        if not _timestamp_after_horizon(ts, signal_time, horizon_hours):
            continue
        if ts > now:
            continue
        candidates.append(PriceHit(price, 'scanner_data', ts))

    hist = _historical_close_after_horizon(ticker, signal_time, horizon_hours)
    if hist is not None:
        price, day = hist
        day_ts = _parse_timestamp(f'{day}T00:00:00+00:00')
        if day_ts is not None and day_ts > signal_time and _timestamp_after_horizon(day_ts, signal_time, horizon_hours):
            if day_ts <= now:
                candidates.append(PriceHit(price, 'historical_close', day_ts))

    if not candidates:
        return None

    candidates.sort(key=lambda hit: hit.timestamp or datetime.min.replace(tzinfo=timezone.utc))
    return candidates[-1]


def _market_price_entry(data: dict, ticker: str) -> tuple[float, Any] | None:
    prices = data.get('prices')
    if not isinstance(prices, dict):
        return None
    symbol = str(ticker).strip().upper()
    match_key = symbol if symbol in prices else None
    if match_key is None:
        for key in prices:
            if str(key).strip().upper() == symbol:
                match_key = key
                break
    if match_key is None:
        return None
    entry = prices.get(match_key)
    if isinstance(entry, (int, float)) and not isinstance(entry, bool):
        return float(entry), entry
    if isinstance(entry, dict):
        price = _extract_price_from_mapping(entry)
        if price is not None:
            return price, entry
    price = _to_float(entry)
    if price is not None:
        return price, entry
    return None


def _historical_close_on_or_before(ticker: str, signal_time: datetime | None) -> tuple[float, str] | None:
    if signal_time is None:
        return None
    try:
        from backend.storage.historical_market_store import get_historical_db_path, get_prices

        if not get_historical_db_path().exists():
            return None
        rows = get_prices(
            ticker=ticker,
            market='NSE',
            to_date=signal_time.date().isoformat(),
            limit=5,
        )
        for row in reversed(rows):
            if int(row.get('fake_prices') or 0):
                continue
            close = _to_float(row.get('close'))
            day = row.get('date')
            if close is not None and close > 0 and day:
                return close, str(day)
    except Exception:
        return None
    return None


def _historical_close_after_horizon(
    ticker: str,
    signal_time: datetime,
    horizon_hours: float,
) -> tuple[float, str] | None:
    try:
        from backend.storage.historical_market_store import get_historical_db_path, get_prices

        if not get_historical_db_path().exists():
            return None
        min_dt = signal_time + timedelta(hours=horizon_hours)
        rows = get_prices(
            ticker=ticker,
            market='NSE',
            from_date=min_dt.date().isoformat(),
            limit=10,
        )
        for row in rows:
            if int(row.get('fake_prices') or 0):
                continue
            close = _to_float(row.get('close'))
            day = row.get('date')
            if close is not None and close > 0 and day:
                return close, str(day)
    except Exception:
        return None
    return None


def prediction_has_reference_price(prediction: dict) -> bool:
    raw = parse_prediction_raw_payload(prediction.get('raw_payload'))
    stack = _parse_signal_stack(prediction)
    for container in (stack, raw):
        if _extract_price_from_mapping(container) is not None:
            return True
    return False


def analyze_prediction_price_coverage(
    prediction: dict,
    *,
    store: OutcomePriceStore | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return per-prediction coverage flags for reporting."""
    from backend.storage.outcome_resolver import _extract_horizon, _horizon_due, _signal_time

    store = store or OutcomePriceStore.load()
    now = now or datetime.now(timezone.utc)
    signal_time = _signal_time(prediction)
    horizon = _extract_horizon(prediction)
    ref = lookup_reference_price(prediction, signal_time, store)
    eval_hit = None
    resolvable = False
    if signal_time is not None and _horizon_due(signal_time, horizon, now=now):
        eval_hit = lookup_evaluation_price(
            prediction,
            signal_time,
            horizon,
            store=store,
            now=now,
        )
        if ref is not None and eval_hit is not None:
            from backend.storage.outcome_resolver import HORIZON_MIN_HOURS
            from backend.storage.outcome_price_lookup import validate_resolution_price_pair

            horizon_hours = float(HORIZON_MIN_HOURS.get(horizon, HORIZON_MIN_HOURS['UNKNOWN']))
            resolvable = validate_resolution_price_pair(ref, eval_hit, signal_time, horizon_hours)
    return {
        'ticker': str(prediction.get('ticker') or '').strip().upper(),
        'has_reference_price': ref is not None,
        'has_evaluation_price': eval_hit is not None,
        'resolvable_now': resolvable,
        'reference_source': ref.source if ref else None,
        'evaluation_source': eval_hit.source if eval_hit else None,
    }


def build_price_coverage_report(*, limit: int = 1000) -> dict[str, Any]:
    from backend.storage.outcome_resolver import get_pending_predictions

    store = OutcomePriceStore.load()
    pending = get_pending_predictions(limit=limit)
    missing_ref = missing_eval = missing_both = resolvable = has_ref = has_eval = 0
    missing_tickers: dict[str, int] = {}

    for prediction in pending:
        cov = analyze_prediction_price_coverage(prediction, store=store)
        ticker = cov.get('ticker') or '?'
        if cov.get('has_reference_price'):
            has_ref += 1
        else:
            missing_ref += 1
            missing_tickers[ticker] = missing_tickers.get(ticker, 0) + 1
        if cov.get('has_evaluation_price'):
            has_eval += 1
        else:
            missing_eval += 1
            if not cov.get('has_reference_price'):
                missing_both += 1
        if cov.get('resolvable_now'):
            resolvable += 1

    top_missing = sorted(missing_tickers.items(), key=lambda item: (-item[1], item[0]))[:10]
    return {
        'pending_total': len(pending),
        'has_reference_price': has_ref,
        'has_evaluation_price': has_eval,
        'resolvable_now': resolvable,
        'missing_reference': missing_ref,
        'missing_evaluation': missing_eval,
        'missing_both': missing_both,
        'top_missing_tickers': [ticker for ticker, _count in top_missing],
    }


def backfill_prediction_reference_prices(
    *,
    dry_run: bool = True,
    force: bool = False,
    limit: int = 500,
) -> dict[str, Any]:
    from backend.storage.market_memory_db import init_market_memory_db, upsert_prediction
    from backend.storage.outcome_resolver import _signal_time, get_pending_predictions

    store = OutcomePriceStore.load()
    summary = {
        'dry_run': dry_run,
        'force': force,
        'candidates': 0,
        'updated': 0,
        'skipped_no_price': 0,
        'errors': 0,
    }
    if not init_market_memory_db():
        summary['errors'] += 1
        return summary

    for prediction in get_pending_predictions(limit=limit):
        if prediction_has_reference_price(prediction) and not force:
            continue
        signal_time = _signal_time(prediction)
        hit = lookup_reference_price(prediction, signal_time, store)
        if hit is None:
            summary['skipped_no_price'] += 1
            continue
        summary['candidates'] += 1
        if dry_run:
            continue

        raw = parse_prediction_raw_payload(prediction.get('raw_payload'))
        raw['reference_price'] = hit.price
        if _extract_price_from_mapping(raw) is None:
            raw['entry_price'] = hit.price
        raw['reference_price_source'] = hit.source
        if hit.timestamp is not None:
            raw['reference_price_timestamp'] = hit.timestamp.isoformat()

        payload = dict(prediction)
        payload['raw_payload'] = raw
        try:
            if upsert_prediction(payload):
                summary['updated'] += 1
            else:
                summary['errors'] += 1
        except Exception:
            summary['errors'] += 1

    return summary
