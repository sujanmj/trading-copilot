"""Post-market actual learning resolver.

Uses stored EOD/latest prices only. Does not call external AI providers.
"""

from __future__ import annotations

import json
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.market_memory_outcomes import lookup_latest_price, load_latest_market_data
from backend.storage.outcome_resolver import (
    BEARISH_HIT_PCT,
    BEARISH_MISS_PCT,
    BULLISH_HIT_PCT,
    BULLISH_MISS_PCT,
    refresh_memory_dashboard_cache,
)
from backend.utils.safe_stdio import safe_print

IST = ZoneInfo('Asia/Kolkata')
HOLDING_PERIOD = 'actual_learning'
RESOLVER_VERSION = '4A'
LEARNING_PACK_VERSION = '4A3_price_bridge'

STATE_FILE_NAME = 'actual_learning_last_run.json'
CANDIDATE_FILE_NAME = 'actual_learning_candidates.jsonl'
INDIA_MARKET_OPEN_TIME = dt_time(9, 15)

WIN = 'WIN'
LOSS = 'LOSS'
NEUTRAL = 'NEUTRAL'
NO_FILL = 'NO_FILL'
AVOID_SUCCESS = 'AVOID_SUCCESS'
AVOID_FAIL = 'AVOID_FAIL'
MISSED_OPPORTUNITY = 'MISSED_OPPORTUNITY'

NON_WL_OUTCOMES = frozenset({NO_FILL, MISSED_OPPORTUNITY})

CLOSE_PRICE_FIELDS = (
    'close',
    'last_price',
    'ltp',
    'price',
    'current_price',
)

REFERENCE_PRICE_FIELDS = (
    'signal_price',
    'price_at_signal',
    'reference_price',
    'entry_price',
    'entry',
)


def _now_ist() -> datetime:
    return datetime.now(IST)


def _today() -> str:
    return _now_ist().date().isoformat()


def _state_path() -> Path:
    return get_data_path(STATE_FILE_NAME)


def _candidate_path(path: Path | None = None) -> Path:
    return path or get_data_path(CANDIDATE_FILE_NAME)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ''):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ticker(row: dict[str, Any]) -> str:
    return str(row.get('ticker') or row.get('symbol') or row.get('name') or '').strip().upper()


def _timestamp(row: dict[str, Any], session_date: str) -> str:
    for key in ('timestamp', 'time', 'generated_at', 'created_at', 'sampled_at', 'date'):
        value = row.get(key)
        if value:
            return str(value)
    return f'{session_date}T15:30:00+05:30'


def _signal_price(row: dict[str, Any]) -> float | None:
    for key in ('signal_price', 'price_at_signal', 'entry_price', 'reference_price', 'current_price', 'price'):
        val = _safe_float(row.get(key))
        if val is not None and val > 0:
            return val
    return None


def _score(row: dict[str, Any]) -> float | None:
    for key in ('score', 'final_score', 'confidence'):
        val = _safe_float(row.get(key))
        if val is not None:
            return val
    return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip()
        if len(text) == 10:
            text = f'{text}T00:00:00+05:30'
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        return parsed
    except Exception:
        return None


def _dt_session_date(value: datetime | None) -> str:
    if value is None:
        return ''
    return value.astimezone(IST).date().isoformat()


def _iso_dt(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ''


def _market_mode_token(value: Any) -> str:
    return str(value or '').strip().upper().replace(' ', '_')


def _is_after_hours_eod_mode(market_mode: Any) -> bool:
    token = _market_mode_token(market_mode)
    return 'AFTER_HOURS' in token or 'POSTMARKET' in token


def _resolve_learning_market_mode(
    market_data: dict[str, Any] | None = None,
    *,
    market_mode: str | None = None,
) -> str:
    explicit = _market_mode_token(market_mode)
    if explicit:
        return explicit
    if isinstance(market_data, dict):
        for key in ('market_mode', 'mode', 'phase', 'active_mode'):
            token = _market_mode_token(market_data.get(key))
            if token:
                return token
    try:
        from backend.telegram.india_mode_lock import resolve_telegram_market_phase

        return _market_mode_token(resolve_telegram_market_phase())
    except Exception:
        return ''


def _is_after_market_open_ts(value: datetime | None) -> bool:
    if value is None:
        return False
    return value.astimezone(IST).time() >= INDIA_MARKET_OPEN_TIME


def _log_eod_freshness_policy(
    *,
    market_mode: str,
    symbol: str,
    timestamp: datetime | None,
    status: str,
    reason: str,
) -> None:
    safe_print(
        f"[EOD_FRESHNESS_POLICY] mode={market_mode or '-'} symbol={symbol or '-'} "
        f"ts={_iso_dt(timestamp) or '-'} status={status} reason={reason}",
        flush=True,
    )


def _same_utc_timestamp(left: Any, right: Any) -> bool:
    left_dt = _parse_dt(left)
    right_dt = _parse_dt(right)
    if left_dt is None or right_dt is None:
        return False
    return left_dt.astimezone(timezone.utc) == right_dt.astimezone(timezone.utc)


def _same_price(left: Any, right: Any) -> bool:
    left_price = _safe_float(left)
    right_price = _safe_float(right)
    if left_price is None or right_price is None:
        return False
    return abs(left_price - right_price) <= 1e-9


def _base_price_source(source: Any) -> str:
    text = str(source or '')
    return text.split(':', 1)[0]


def _price_delta_evidence_guard(
    *,
    symbol: str,
    ref: dict[str, Any],
    close: dict[str, Any],
) -> tuple[bool, str]:
    ref_ts = _parse_dt(ref.get('timestamp'))
    close_ts = _parse_dt(close.get('timestamp'))
    ref_price = _safe_float(ref.get('price'))
    close_price = _safe_float(close.get('price'))
    ref_source = str(ref.get('source') or '')
    close_source = str(close.get('source') or '')
    same_timestamp = (
        ref_ts is not None
        and close_ts is not None
        and ref_ts.astimezone(timezone.utc) == close_ts.astimezone(timezone.utc)
    )
    same_price = _same_price(ref_price, close_price)
    same_source = _base_price_source(ref_source) == _base_price_source(close_source)

    if ref_ts is None or close_ts is None:
        return False, 'no_independent_reference'
    if same_timestamp and same_price and (same_source or ref_source.endswith(':first_after_emit')):
        return False, 'same_price_snapshot'
    if same_timestamp:
        return False, 'same_timestamp'
    if ref_source.endswith(':first_after_emit') and same_source and same_price and same_timestamp:
        return False, 'same_price_snapshot'
    if same_price:
        return True, 'genuine_zero_move'
    return True, 'independent_price_points'


def _log_zero_move_guard(*, symbol: str, accepted: bool, reason: str) -> None:
    safe_print(
        f"[ZERO_MOVE_GUARD] symbol={symbol or '-'} "
        f"status={'accepted' if accepted else 'pending'} reason={reason}",
        flush=True,
    )


def _log_price_delta_evidence(
    *,
    symbol: str,
    ref: dict[str, Any],
    close: dict[str, Any],
    status: str,
) -> None:
    safe_print(
        f"[PRICE_DELTA_EVIDENCE] symbol={symbol or '-'} "
        f"ref={_safe_float(ref.get('price'))} ref_ts={ref.get('timestamp') or '-'} "
        f"close={_safe_float(close.get('price'))} close_ts={close.get('timestamp') or '-'} "
        f"status={status}",
        flush=True,
    )


def _has_independent_price_delta(evidence: dict[str, Any] | None) -> bool:
    if not isinstance(evidence, dict) or evidence.get('status') != 'valid':
        return False
    ref_ts = evidence.get('ref_timestamp')
    close_ts = evidence.get('close_timestamp')
    if not ref_ts or not close_ts:
        return False
    return not _same_utc_timestamp(ref_ts, close_ts)


def _price_from_row(row: dict[str, Any]) -> float | None:
    for key in CLOSE_PRICE_FIELDS:
        val = _safe_float(row.get(key))
        if val is not None and val > 0:
            return val
    return None


def _reference_price_from_row(row: dict[str, Any]) -> float | None:
    for key in REFERENCE_PRICE_FIELDS:
        val = _safe_float(row.get(key))
        if val is not None and val > 0:
            return val
    return None


def _category_from_row(row: dict[str, Any], default: str) -> str:
    explicit = str(row.get('learning_category') or row.get('category') or '').strip().lower()
    if explicit in ('tradecard', 'top_watch', 'watchlist', 'scanner_watch', 'avoid', 'missed'):
        return 'top_watch' if explicit == 'watchlist' else explicit
    action = str(row.get('action') or row.get('status') or row.get('entry_status') or '').upper()
    if 'MISSED' in action:
        return 'missed'
    if 'AVOID' in action or 'REJECT' in action or 'BEARISH' in action:
        return 'avoid'
    return default


def _is_next_session_only(row: dict[str, Any]) -> bool:
    text = ' '.join(str(row.get(k) or '') for k in ('action', 'status', 'reason', 'path_note', 'entry_status'))
    upper = text.upper()
    return (
        'NEXT-SESSION WATCH' in upper
        or 'NEXT_SESSION_WATCH' in upper
        or 'NO ACTIVE ENTRY' in upper
        or str(row.get('carry_forward_next_session') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    )


def record_learning_candidate(
    *,
    symbol: str | None = None,
    ticker: str | None = None,
    emitted_at: str | None = None,
    trading_date: str | None = None,
    source: str = '',
    reference_price: Any = None,
    reference_price_source: str = '',
    scanner_timestamp: str | None = None,
    initial_move: Any = None,
    volume: Any = None,
    direction: str = 'BULLISH',
    score: Any = None,
    category: str = '',
    raw: dict[str, Any] | None = None,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Persist a sent/emitted symbol as a future EOD learning candidate."""
    sym = str(symbol or ticker or '').strip().upper()
    ts = emitted_at or _now_ist().isoformat()
    day = trading_date or _dt_session_date(_parse_dt(ts)) or _today()
    row = {
        'symbol': sym,
        'emitted_at': ts,
        'trading_date': day,
        'source': str(source or 'unknown'),
        'reference_price': _safe_float(reference_price),
        'reference_price_source': str(reference_price_source or ''),
        'scanner_timestamp': scanner_timestamp or '',
        'initial_move': _safe_float(initial_move),
        'volume': _safe_float(volume),
        'direction': str(direction or 'BULLISH').upper(),
        'score': _safe_float(score),
        'category': str(category or ''),
        'raw': dict(raw or {}),
        'recorded_at': _now_ist().isoformat(),
    }
    if not sym:
        return row
    try:
        path = _candidate_path(state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
        safe_print(
            f"[LEARNING_CANDIDATE_CAPTURE] symbol={sym} source={row['source']} "
            f"ref={row['reference_price']} ts={ts}",
            flush=True,
        )
    except Exception:
        pass
    return row


def load_learning_candidates_for_date(
    session_date: str,
    *,
    state_path: Path | None = None,
) -> list[dict[str, Any]]:
    path = _candidate_path(state_path)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            emitted = _parse_dt(row.get('emitted_at'))
            day = str(row.get('trading_date') or _dt_session_date(emitted) or '')
            if day == session_date:
                rows.append(row)
    except Exception:
        return []
    return rows


def _candidate_store_candidates(session_date: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in load_learning_candidates_for_date(session_date):
        sym = str(row.get('symbol') or row.get('ticker') or '').strip().upper()
        if not sym:
            continue
        source = str(row.get('source') or 'learning_candidate_store')
        category = str(row.get('category') or '').strip().lower()
        if category not in ('top_watch', 'scanner_watch', 'avoid', 'missed', 'tradecard'):
            if str(row.get('direction') or '').upper() == 'BEARISH' or 'avoid' in source.lower():
                category = 'avoid'
            elif 'intraday' in source.lower() or 'open' in source.lower():
                category = 'scanner_watch'
            else:
                category = 'top_watch'
        item = _candidate(
            {
                'ticker': sym,
                'timestamp': row.get('emitted_at'),
                'direction': row.get('direction') or 'BULLISH',
                'score': row.get('score'),
                'price': row.get('reference_price'),
                'reference_price': row.get('reference_price'),
                'volume_ratio': row.get('volume'),
                'reason': source,
            },
            category=category,
            session_date=session_date,
            source=source,
        )
        if item:
            raw = item.get('raw') if isinstance(item.get('raw'), dict) else {}
            raw['learning_candidate_record'] = dict(row)
            item['raw'] = raw
            out.append(item)
    return out


def _candidate(
    row: dict[str, Any],
    *,
    category: str,
    session_date: str,
    source: str,
) -> dict[str, Any] | None:
    sym = _ticker(row)
    if not sym or _is_next_session_only(row):
        return None
    direction = 'BEARISH' if category == 'avoid' else 'BULLISH'
    if str(row.get('direction') or '').strip().upper() == 'BEARISH':
        direction = 'BEARISH'
    return {
        'ticker': sym,
        'category': category,
        'source': source,
        'timestamp': _timestamp(row, session_date),
        'direction': direction,
        'signal_price': _signal_price(row),
        'score': _score(row),
        'raw': dict(row),
    }


def _alert_event_candidates(session_date: str) -> list[dict[str, Any]]:
    try:
        from backend.orchestration.alert_event_log import read_alert_events_for_date

        rows = read_alert_events_for_date(session_date)
    except Exception:
        rows = []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        alert_type = str(row.get('alert_type') or '').lower()
        direction = str(row.get('direction') or '').upper()
        category = 'scanner_watch' if alert_type in ('open', 'intraday') else 'top_watch'
        if direction == 'BEARISH' or 'avoid' in str(row.get('reason_preview') or '').lower():
            category = 'avoid'
        for ticker in row.get('tickers') or []:
            item = _candidate(
                {
                    'ticker': ticker,
                    'timestamp': row.get('timestamp'),
                    'direction': direction or 'BULLISH',
                    'score': row.get('score') or row.get('confidence'),
                    'price': row.get('price_at_alert'),
                    'volume_ratio': row.get('volume_at_alert'),
                    'reason': row.get('reason_preview'),
                    'alert_type': alert_type,
                },
                category=category,
                session_date=session_date,
                source='alert_event_log',
            )
            if item:
                out.append(item)
    return out


def _quality_state_signature_candidates(session_date: str) -> list[dict[str, Any]]:
    try:
        from backend.orchestration import alert_quality_engine as aq

        state = aq._load_json(aq.STATE_FILE, {})  # type: ignore[attr-defined]
    except Exception:
        state = {}
    if not isinstance(state, dict) or state.get('date') != session_date:
        return []
    sig = state.get('premarket_last_signature') if isinstance(state.get('premarket_last_signature'), dict) else {}
    if sig.get('date') and sig.get('date') != session_date:
        return []
    out: list[dict[str, Any]] = []
    for row in sig.get('rows') or []:
        if not isinstance(row, dict):
            continue
        category = _category_from_row(row, 'top_watch')
        item = _candidate(
            {
                **row,
                'timestamp': f'{session_date}T09:15:00+05:30',
                'reason': row.get('reason') or row.get('action'),
            },
            category=category,
            session_date=session_date,
            source='alert_quality_signature',
        )
        if item:
            out.append(item)
    return out


def _suppression_sent_candidates(session_date: str) -> list[dict[str, Any]]:
    try:
        from backend.orchestration import alert_suppression_log as asl

        rows = [
            row for row in asl._iter_entries(800)  # type: ignore[attr-defined]
            if row.get('date') == session_date and row.get('type') == 'sent'
        ]
    except Exception:
        rows = []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get('ticker') or '').strip().upper()
        if not ticker:
            continue
        category = 'scanner_watch' if 'INTRADAY' in str(row.get('category') or '').upper() else 'top_watch'
        item = _candidate(
            {
                'ticker': ticker,
                'timestamp': row.get('time'),
                'score': row.get('confidence'),
                'reason': row.get('detail'),
            },
            category=category,
            session_date=session_date,
            source='alert_suppression_sent',
        )
        if item:
            out.append(item)
    return out


def _scanner_saved_candidates(session_date: str) -> list[dict[str, Any]]:
    scanner = _load_json(get_data_path('scanner_data.json'))
    if not scanner:
        return []
    scan_ts = None
    for key in ('last_updated', 'scan_time_local', 'generated_at', 'timestamp'):
        scan_ts = _parse_dt(scanner.get(key))
        if scan_ts is not None:
            break
    if scan_ts is None or _dt_session_date(scan_ts) != session_date:
        return []
    out: list[dict[str, Any]] = []
    for row in _rows_from_payload(scanner, 'top_signals', 'signals'):
        category = _category_from_row(row, 'scanner_watch')
        item = _candidate(
            {
                **row,
                'timestamp': row.get('timestamp') or scan_ts.isoformat(),
            },
            category=category,
            session_date=session_date,
            source='scanner_data_today',
        )
        if item:
            out.append(item)
    return out


def _emitted_source_candidates(session_date: str) -> list[dict[str, Any]]:
    return _dedupe_candidates(
        _alert_event_candidates(session_date)
        + _candidate_store_candidates(session_date)
        + _quality_state_signature_candidates(session_date)
        + _suppression_sent_candidates(session_date)
        + _scanner_saved_candidates(session_date)
    )


def _tradecard_candidates(session_date: str) -> list[dict[str, Any]]:
    try:
        from backend.trading.tradecard_journal import summarize_today_outcomes

        rows = summarize_today_outcomes(session_date=session_date).get('rows') or []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get('status') or '').upper() != 'VALID_ENTRY':
            continue
        if _is_next_session_only(row):
            continue
        sym = _ticker(row)
        if not sym:
            continue
        out.append({
            'ticker': sym,
            'category': 'tradecard',
            'source': 'tradecard_journal',
            'timestamp': str(row.get('created_at') or row.get('generated_at') or f'{session_date}T15:30:00+05:30'),
            'direction': 'BULLISH',
            'signal_price': _safe_float(row.get('price_at_signal')),
            'score': None,
            'raw': dict(row),
        })
    return out


def _missed_candidates(session_date: str) -> list[dict[str, Any]]:
    try:
        from backend.orchestration.alert_quality_engine import missed_opportunities_summary

        rows = missed_opportunities_summary(limit=200).get('rows') or []
    except Exception:
        rows = []
    out = []
    for row in rows:
        item = _candidate(row, category='missed', session_date=session_date, source='missed_opportunities')
        if item:
            out.append(item)
    return out


def _rows_from_payload(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in keys:
        val = payload.get(key)
        if isinstance(val, list):
            rows.extend([r for r in val if isinstance(r, dict)])
        elif isinstance(val, dict):
            rows.append(val)
    return rows


def _source_candidates(session_date: str, sources: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if sources is None:
        candidates = _tradecard_candidates(session_date)
        candidates.extend(_emitted_source_candidates(session_date))
        candidates.extend(_missed_candidates(session_date))
        return _dedupe_candidates(candidates)

    candidates: list[dict[str, Any]] = []
    for row in sources.get('tradecards') or []:
        if isinstance(row, dict):
            item = _candidate(row, category='tradecard', session_date=session_date, source='tradecard_test')
            if item:
                candidates.append(item)
    if 'tradecards' not in sources:
        candidates.extend(_tradecard_candidates(session_date))

    for source_name, payload in (
        ('stock_today', sources.get('stock_today') or {}),
        ('final_confidence', sources.get('final_confidence') or {}),
    ):
        if isinstance(payload, dict):
            for row in _rows_from_payload(payload, 'top_pick', 'ranked_candidates', 'top_candidates', 'rows'):
                category = _category_from_row(row, 'top_watch')
                item = _candidate(row, category=category, session_date=session_date, source=source_name)
                if item:
                    candidates.append(item)

    pack = sources.get('daily_pack') or {}
    if isinstance(pack, dict):
        tw = pack.get('tomorrow_watchlist') if isinstance(pack.get('tomorrow_watchlist'), dict) else {}
        for row in _rows_from_payload(tw, 'top_watchlist', 'raw_candidates'):
            item = _candidate(row, category='top_watch', session_date=session_date, source='daily_pack_watchlist')
            if item:
                candidates.append(item)
        for row in _rows_from_payload(tw, 'avoid'):
            item = _candidate(row, category='avoid', session_date=session_date, source='daily_pack_avoid')
            if item:
                candidates.append(item)

    tw_report = sources.get('tomorrow_watchlist') or {}
    if isinstance(tw_report, dict):
        for row in _rows_from_payload(tw_report, 'top_watchlist', 'raw_candidates'):
            item = _candidate(row, category='top_watch', session_date=session_date, source='watchlist_report')
            if item:
                candidates.append(item)
        for row in _rows_from_payload(tw_report, 'avoid'):
            item = _candidate(row, category='avoid', session_date=session_date, source='watchlist_report')
            if item:
                candidates.append(item)

    scanner = sources.get('scanner') or {}
    if isinstance(scanner, dict):
        for row in _rows_from_payload(scanner, 'top_signals', 'signals'):
            category = _category_from_row(row, 'scanner_watch')
            item = _candidate(row, category=category, session_date=session_date, source='scanner_data')
            if item:
                candidates.append(item)

    for row in sources.get('missed') or []:
        if isinstance(row, dict):
            item = _candidate(row, category='missed', session_date=session_date, source='missed_test')
            if item:
                candidates.append(item)
    if 'missed' not in sources:
        candidates.extend(_missed_candidates(session_date))

    return _dedupe_candidates(candidates)


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {
        'tradecard': 0,
        'top_watch': 1,
        'scanner_watch': 2,
        'avoid': 3,
        'missed': 4,
    }
    picked: dict[tuple[str, str], dict[str, Any]] = {}
    for item in candidates:
        group = item.get('category')
        if group in ('top_watch', 'scanner_watch'):
            group = 'bullish_watch'
        key = (str(item.get('ticker') or ''), str(group or ''))
        existing = picked.get(key)
        if existing is None or priority.get(str(item.get('category')), 99) < priority.get(str(existing.get('category')), 99):
            picked[key] = item
    return list(picked.values())


def _iter_nested_rows(node: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if _ticker(node):
            rows.append(node)
        for val in node.values():
            rows.extend(_iter_nested_rows(val))
    elif isinstance(node, list):
        for item in node:
            rows.extend(_iter_nested_rows(item))
    return rows


def _latest_price_entry(market_data: dict[str, Any], ticker: str) -> dict[str, Any]:
    prices = market_data.get('prices') if isinstance(market_data, dict) else {}
    if not isinstance(prices, dict):
        return {}
    for key, val in prices.items():
        if str(key).strip().upper() != ticker:
            continue
        if isinstance(val, dict):
            return val
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return {'price': float(val)}
    return {}


def _row_timestamp(row: dict[str, Any], fallback: datetime | None = None) -> datetime | None:
    for key in ('validated_at', 'timestamp', 'as_of', 'last_updated', 'generated_at', 'scan_time_local', 'time'):
        ts = _parse_dt(row.get(key))
        if ts is not None:
            return ts
    return fallback


def _market_data_price_hits(
    data: dict[str, Any] | None,
    *,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(data, dict):
        return {}
    file_ts = None
    for key in ('last_updated', 'generated_at', 'timestamp', 'as_of'):
        file_ts = _parse_dt(data.get(key))
        if file_ts is not None:
            break
    prices = data.get('prices')
    if not isinstance(prices, dict):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for key, val in prices.items():
        ticker = str(key).strip().upper()
        if not ticker:
            continue
        if isinstance(val, dict):
            price = _price_from_row(val)
            ts = _row_timestamp(val, file_ts)
            high = _safe_float(val.get('high'))
            low = _safe_float(val.get('low'))
        else:
            price = _safe_float(val)
            ts = file_ts
            high = None
            low = None
        if price is None or price <= 0:
            continue
        out.setdefault(ticker, []).append({
            'ticker': ticker,
            'price': price,
            'timestamp': _iso_dt(ts),
            'source': source,
            'high': high,
            'low': low,
            'raw': val if isinstance(val, dict) else {'price': price},
        })
    return out


def _market_data_context(
    data: dict[str, Any] | None,
    *,
    source: str,
) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    ts = None
    for key in ('last_updated', 'generated_at', 'timestamp', 'as_of'):
        ts = _parse_dt(data.get(key))
        if ts is not None:
            break
    if ts is None:
        return None
    return {
        'source': source,
        'timestamp': _iso_dt(ts),
        'session_date': _dt_session_date(ts),
    }


def _scanner_global_context() -> dict[str, Any] | None:
    scanner = _load_json(get_data_path('scanner_data.json'))
    if not scanner:
        return None
    ts = None
    for key in ('last_updated', 'scan_time_local', 'generated_at', 'timestamp'):
        ts = _parse_dt(scanner.get(key))
        if ts is not None:
            break
    if ts is None:
        return None
    return {
        'source': 'scanner_data',
        'timestamp': _iso_dt(ts),
        'session_date': _dt_session_date(ts),
    }


def _scanner_price_hits() -> dict[str, list[dict[str, Any]]]:
    scanner = _load_json(get_data_path('scanner_data.json'))
    if not scanner:
        return {}
    fallback = None
    for key in ('last_updated', 'scan_time_local', 'generated_at', 'timestamp'):
        fallback = _parse_dt(scanner.get(key))
        if fallback is not None:
            break
    out: dict[str, list[dict[str, Any]]] = {}
    for row in _rows_from_payload(scanner, 'top_signals', 'all_signals', 'signals'):
        ticker = _ticker(row)
        price = _price_from_row(row)
        if not ticker or price is None or price <= 0:
            continue
        ts = _row_timestamp(row, fallback)
        out.setdefault(ticker, []).append({
            'ticker': ticker,
            'price': price,
            'timestamp': _iso_dt(ts),
            'source': 'scanner_data',
            'high': _safe_float(row.get('high')),
            'low': _safe_float(row.get('low')),
            'raw': dict(row),
        })
    return out


def _active_prediction_price_hits() -> dict[str, list[dict[str, Any]]]:
    data = _load_json(get_data_path('active_predictions.json'))
    if not data:
        return {}
    fallback = None
    for key in ('generated_at', 'last_updated', 'timestamp', 'as_of'):
        fallback = _parse_dt(data.get(key))
        if fallback is not None:
            break
    out: dict[str, list[dict[str, Any]]] = {}
    for row in _iter_nested_rows(data):
        ticker = _ticker(row)
        price = _price_from_row(row)
        if not ticker or price is None or price <= 0:
            continue
        ts = _row_timestamp(row, fallback)
        out.setdefault(ticker, []).append({
            'ticker': ticker,
            'price': price,
            'timestamp': _iso_dt(ts),
            'source': 'active_predictions',
            'high': _safe_float(row.get('high')),
            'low': _safe_float(row.get('low')),
            'raw': dict(row),
        })
    return out


def _merge_hits(*groups: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = {}
    for group in groups:
        for ticker, rows in group.items():
            merged.setdefault(ticker, []).extend(rows)
    return merged


def capture_eod_price_evidence(
    symbols: list[str],
    *,
    session_date: str,
    market_data: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Collect real same-day price evidence from local runtime sources."""
    symbol_set = {str(sym or '').strip().upper() for sym in symbols if str(sym or '').strip()}
    evidence = _merge_hits(
        _market_data_price_hits(market_data, source='runtime_market_data') if market_data is not None else {},
        _market_data_price_hits(load_latest_market_data(get_data_path('latest_market_data_memory_enriched.json')), source='latest_market_data_memory_enriched'),
        _market_data_price_hits(load_latest_market_data(get_data_path('latest_market_data.json')), source='latest_market_data'),
        _scanner_price_hits(),
        _active_prediction_price_hits(),
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for ticker in symbol_set:
        out[ticker] = list(evidence.get(ticker) or [])
    return out


def capture_eod_price_context(market_data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return global freshness context for runtime/scanner sources."""
    contexts: list[dict[str, Any]] = []
    for ctx in (
        _market_data_context(market_data, source='runtime_market_data') if market_data is not None else None,
        _market_data_context(load_latest_market_data(get_data_path('latest_market_data_memory_enriched.json')), source='latest_market_data_memory_enriched'),
        _market_data_context(load_latest_market_data(get_data_path('latest_market_data.json')), source='latest_market_data'),
        _scanner_global_context(),
    ):
        if ctx:
            contexts.append(ctx)
    return contexts


def _has_fresh_global_context(
    contexts: list[dict[str, Any]] | None,
    *,
    session_date: str,
    after_timestamp: datetime | None,
    market_mode: str = '',
) -> bool:
    after_hours = _is_after_hours_eod_mode(market_mode)
    for ctx in contexts or []:
        ts = _parse_dt(ctx.get('timestamp'))
        if ts is None or _dt_session_date(ts) != session_date:
            continue
        if after_hours:
            if _is_after_market_open_ts(ts):
                return True
            continue
        if after_timestamp is not None and ts.astimezone(timezone.utc) <= after_timestamp.astimezone(timezone.utc):
            continue
        return True
    return False


def _active_prediction_reference_evidence(ticker: str, *, session_date: str) -> dict[str, Any] | None:
    symbol = str(ticker or '').upper()
    if not symbol:
        return None
    data = _load_json(get_data_path('active_predictions.json'))
    if not data:
        return None
    fallback = None
    for key in ('generated_at', 'last_updated', 'timestamp', 'as_of'):
        fallback = _parse_dt(data.get(key))
        if fallback is not None:
            break
    candidates: list[dict[str, Any]] = []
    for row in _iter_nested_rows(data):
        if _ticker(row) != symbol:
            continue
        price = _reference_price_from_row(row)
        if price is None:
            continue
        ts = _row_timestamp(row, fallback)
        if _dt_session_date(ts) != session_date:
            continue
        candidates.append({
            'ticker': symbol,
            'price': price,
            'timestamp': _iso_dt(ts),
            'source': 'active_predictions',
        })
    if not candidates:
        return None
    candidates.sort(key=lambda row: _parse_dt(row.get('timestamp')) or datetime.min.replace(tzinfo=timezone.utc))
    return candidates[0]


def _reference_price_evidence(
    item: dict[str, Any],
    *,
    session_date: str,
    evidence_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    signal = _safe_float(item.get('signal_price'))
    ticker = str(item.get('ticker') or '').upper()
    signal_ts = _parse_dt(item.get('timestamp'))
    if signal is not None and signal > 0:
        if signal_ts is None:
            return None, 'no_reference_price'
        if _dt_session_date(signal_ts) != session_date:
            return None, 'wrong_date'
        return {
            'ticker': ticker,
            'price': signal,
            'timestamp': _iso_dt(signal_ts),
            'source': str(item.get('source') or 'signal'),
        }, 'valid'
    fallback = _active_prediction_reference_evidence(ticker, session_date=session_date)
    if fallback is not None:
        return fallback, 'valid'
    rows = (evidence_by_symbol or {}).get(ticker) or []
    valid: list[dict[str, Any]] = []
    for row in rows:
        price = _safe_float(row.get('price'))
        ts = _parse_dt(row.get('timestamp'))
        if price is None or price <= 0 or ts is None:
            continue
        if _dt_session_date(ts) != session_date:
            continue
        if signal_ts is not None and ts.astimezone(timezone.utc) < signal_ts.astimezone(timezone.utc):
            continue
        valid.append(row)
    if valid:
        valid.sort(key=lambda row: _parse_dt(row.get('timestamp')) or datetime.min.replace(tzinfo=timezone.utc))
        first = valid[0]
        return {
            'ticker': ticker,
            'price': _safe_float(first.get('price')),
            'timestamp': first.get('timestamp'),
            'source': f"{first.get('source') or 'price_evidence'}:first_after_emit",
        }, 'valid'
    return None, 'no_reference_price'


def _close_price_evidence(
    item: dict[str, Any],
    *,
    session_date: str,
    evidence_by_symbol: dict[str, list[dict[str, Any]]],
    evidence_context: list[dict[str, Any]] | None = None,
    after_timestamp: datetime | None = None,
    market_mode: str = '',
) -> tuple[dict[str, Any] | None, str]:
    ticker = str(item.get('ticker') or '').upper()
    rows = evidence_by_symbol.get(ticker) or []
    signal_ts = after_timestamp or _parse_dt(item.get('timestamp'))
    after_hours = _is_after_hours_eod_mode(market_mode)
    if not rows:
        if _has_fresh_global_context(
            evidence_context,
            session_date=session_date,
            after_timestamp=signal_ts,
            market_mode=market_mode,
        ):
            _log_eod_freshness_policy(
                market_mode=market_mode,
                symbol=ticker,
                timestamp=None,
                status='rejected',
                reason='missing_symbol_price',
            )
            return None, 'missing_symbol_price'
        _log_eod_freshness_policy(
            market_mode=market_mode,
            symbol=ticker,
            timestamp=None,
            status='rejected',
            reason='missing_eod_price',
        )
        return None, 'missing_eod_price'
    wrong_date_seen = False
    stale_seen = False
    same_day_seen = False
    stale_sources: set[str] = set()
    valid: list[tuple[dict[str, Any], str]] = []
    for row in rows:
        ts = _parse_dt(row.get('timestamp'))
        if ts is None:
            stale_seen = True
            stale_sources.add(str(row.get('source') or 'unknown'))
            _log_eod_freshness_policy(
                market_mode=market_mode,
                symbol=ticker,
                timestamp=None,
                status='rejected',
                reason='stale_price',
            )
            continue
        if _dt_session_date(ts) != session_date:
            wrong_date_seen = True
            _log_eod_freshness_policy(
                market_mode=market_mode,
                symbol=ticker,
                timestamp=ts,
                status='rejected',
                reason='stale_price' if after_hours else 'wrong_date',
            )
            continue
        same_day_seen = True
        if after_hours:
            if not _is_after_market_open_ts(ts):
                stale_seen = True
                stale_sources.add(str(row.get('source') or 'unknown'))
                _log_eod_freshness_policy(
                    market_mode=market_mode,
                    symbol=ticker,
                    timestamp=ts,
                    status='rejected',
                    reason='stale_price',
                )
                continue
            _log_eod_freshness_policy(
                market_mode=market_mode,
                symbol=ticker,
                timestamp=ts,
                status='accepted',
                reason='valid_eod_after_hours',
            )
            valid.append((row, 'valid_eod_after_hours'))
            continue
        if signal_ts is not None and ts.astimezone(timezone.utc) <= signal_ts.astimezone(timezone.utc):
            stale_seen = True
            stale_sources.add(str(row.get('source') or 'unknown'))
            _log_eod_freshness_policy(
                market_mode=market_mode,
                symbol=ticker,
                timestamp=ts,
                status='rejected',
                reason='stale_price',
            )
            continue
        _log_eod_freshness_policy(
            market_mode=market_mode,
            symbol=ticker,
            timestamp=ts,
            status='accepted',
            reason='same_day_eod',
        )
        valid.append((row, 'valid'))
    if not valid:
        if wrong_date_seen and not same_day_seen:
            return None, 'stale_price' if after_hours else 'wrong_date'
        if stale_seen:
            if (
                not after_hours
                and _has_fresh_global_context(
                    evidence_context,
                    session_date=session_date,
                    after_timestamp=signal_ts,
                    market_mode=market_mode,
                )
                and not any(source in {'scanner_data', 'runtime_market_data'} for source in stale_sources)
            ):
                return None, 'missing_symbol_price'
            return None, 'stale_price'
        if _has_fresh_global_context(
            evidence_context,
            session_date=session_date,
            after_timestamp=signal_ts,
            market_mode=market_mode,
        ):
            return None, 'missing_symbol_price'
        return None, 'missing_eod_price'
    valid.sort(key=lambda pair: _parse_dt(pair[0].get('timestamp')) or datetime.min.replace(tzinfo=timezone.utc))
    return valid[-1]


def _build_price_evidence(
    item: dict[str, Any],
    *,
    session_date: str,
    evidence_by_symbol: dict[str, list[dict[str, Any]]],
    evidence_context: list[dict[str, Any]] | None = None,
    market_mode: str = '',
) -> tuple[dict[str, Any] | None, str]:
    ref, ref_reason = _reference_price_evidence(
        item,
        session_date=session_date,
        evidence_by_symbol=evidence_by_symbol,
    )
    if ref is None:
        return None, ref_reason
    ref_ts = _parse_dt(ref.get('timestamp')) or _parse_dt(item.get('timestamp'))
    close, close_reason = _close_price_evidence(
        item,
        session_date=session_date,
        evidence_by_symbol=evidence_by_symbol,
        evidence_context=evidence_context,
        after_timestamp=ref_ts,
        market_mode=market_mode,
    )
    if close is None:
        return None, close_reason
    move = _actual_move(_safe_float(ref.get('price')), _safe_float(close.get('price')))
    if move is None:
        return None, 'missing_eod_price'
    independent, delta_reason = _price_delta_evidence_guard(
        symbol=str(item.get('ticker') or ''),
        ref=ref,
        close=close,
    )
    _log_zero_move_guard(symbol=str(item.get('ticker') or ''), accepted=independent, reason=delta_reason)
    _log_price_delta_evidence(
        symbol=str(item.get('ticker') or ''),
        ref=ref,
        close=close,
        status='valid' if independent else 'pending',
    )
    if not independent:
        return None, 'insufficient_price_delta_evidence'
    return {
        'status': 'valid',
        'ticker': item.get('ticker'),
        'ref_price': _safe_float(ref.get('price')),
        'ref_source': ref.get('source'),
        'ref_timestamp': ref.get('timestamp'),
        'close_price': _safe_float(close.get('price')),
        'close_source': close.get('source'),
        'close_timestamp': close.get('timestamp'),
        'close_reason': close_reason,
        'move_pct': move,
        'independent_price_points': True,
        'price_delta_evidence_status': 'valid',
        'price_delta_evidence_reason': delta_reason,
        'high': close.get('high'),
        'low': close.get('low'),
    }, 'valid'


def _latest_price_evidence(
    market_data: dict[str, Any],
    ticker: str,
    *,
    session_date: str,
    signal_timestamp: str,
) -> tuple[float | None, str]:
    entry = _latest_price_entry(market_data, ticker)
    if not entry:
        return None, 'missing_latest_price'
    latest = lookup_latest_price(market_data, ticker)
    if latest is None or latest <= 0:
        return None, 'missing_latest_price'

    ts = None
    for key in ('validated_at', 'timestamp', 'as_of', 'last_updated', 'generated_at'):
        ts = _parse_dt(entry.get(key))
        if ts is not None:
            break
    if ts is None:
        for key in ('last_updated', 'generated_at', 'timestamp', 'as_of'):
            ts = _parse_dt(market_data.get(key))
            if ts is not None:
                break
    if ts is None:
        return None, 'missing_latest_price_timestamp'
    if _dt_session_date(ts) != session_date:
        return None, 'latest_price_not_current_session'
    signal_ts = _parse_dt(signal_timestamp)
    if signal_ts is not None and ts.astimezone(timezone.utc) <= signal_ts.astimezone(timezone.utc):
        return None, 'latest_price_not_after_signal'
    return latest, 'real_price_after_signal'


def _actual_move(signal_price: float | None, latest_price: float | None) -> float | None:
    if signal_price is None or latest_price is None or signal_price <= 0:
        return None
    return round(((latest_price - signal_price) / signal_price) * 100.0, 4)


def _tradecard_outcome(item: dict[str, Any]) -> tuple[str | None, str | None, float | None]:
    raw = item.get('raw') if isinstance(item.get('raw'), dict) else {}
    outcome = str(raw.get('outcome_status') or '').upper()
    if outcome in ('T1_HIT', 'T2_HIT'):
        return WIN, outcome, _actual_move(item.get('signal_price'), _safe_float(raw.get('outcome_price')))
    if outcome in ('SL_HIT', 'AMBIGUOUS'):
        return LOSS, outcome, _actual_move(item.get('signal_price'), _safe_float(raw.get('outcome_price')))
    if outcome == 'NO_FILL':
        return NO_FILL, NO_FILL, None
    if outcome == 'EXPIRED':
        return NEUTRAL, 'EXPIRED', _actual_move(item.get('signal_price'), _safe_float(raw.get('outcome_price')))
    return None, 'pending_data', None


def _classify_item(
    item: dict[str, Any],
    market_data: dict[str, Any] | None,
    *,
    session_date: str,
    evidence_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    evidence_context: list[dict[str, Any]] | None = None,
    market_mode: str = '',
) -> dict[str, Any]:
    category = str(item.get('category') or '')
    if category == 'tradecard':
        resolved_as, expiry_result, move = _tradecard_outcome(item)
        if resolved_as is None:
            return {'status': 'pending_data', 'reason': expiry_result or 'tradecard pending'}
        return {'status': 'resolved', 'resolved_as': resolved_as, 'expiry_result': expiry_result, 'actual_move': move}

    if not evidence_by_symbol:
        return {'status': 'pending_data', 'reason': 'missing_eod_price'}
    evidence, price_reason = _build_price_evidence(
        item,
        session_date=session_date,
        evidence_by_symbol=evidence_by_symbol or {},
        evidence_context=evidence_context,
        market_mode=market_mode,
    )
    if evidence is None:
        return {'status': 'pending_data', 'reason': price_reason}
    move = _safe_float(evidence.get('move_pct'))

    if category == 'avoid':
        if move <= BEARISH_HIT_PCT:
            return {'status': 'resolved', 'resolved_as': AVOID_SUCCESS, 'expiry_result': AVOID_SUCCESS, 'actual_move': move, 'price_evidence': evidence}
        if move >= BEARISH_MISS_PCT:
            return {'status': 'resolved', 'resolved_as': AVOID_FAIL, 'expiry_result': AVOID_FAIL, 'actual_move': move, 'price_evidence': evidence}
        return {'status': 'resolved', 'resolved_as': NEUTRAL, 'expiry_result': NEUTRAL, 'actual_move': move, 'price_evidence': evidence}
    if category == 'missed':
        return {'status': 'resolved', 'resolved_as': MISSED_OPPORTUNITY, 'expiry_result': MISSED_OPPORTUNITY, 'actual_move': move, 'price_evidence': evidence}

    if move >= BULLISH_HIT_PCT:
        return {'status': 'resolved', 'resolved_as': WIN, 'expiry_result': WIN, 'actual_move': move, 'price_evidence': evidence}
    if move <= BULLISH_MISS_PCT:
        return {'status': 'resolved', 'resolved_as': LOSS, 'expiry_result': LOSS, 'actual_move': move, 'price_evidence': evidence}
    return {'status': 'resolved', 'resolved_as': NEUTRAL, 'expiry_result': NEUTRAL, 'actual_move': move, 'price_evidence': evidence}


def _prediction_payload(item: dict[str, Any], session_date: str) -> dict[str, Any]:
    source = f"actual_learning:{item.get('category')}"
    raw = {
        **(item.get('raw') if isinstance(item.get('raw'), dict) else {}),
        'actual_learning_category': item.get('category'),
        'source': source,
        'prediction_date': session_date,
        'run_type': 'actual_learning',
        'signal_price': item.get('signal_price'),
    }
    return {
        'ticker': item.get('ticker'),
        'timestamp': item.get('timestamp') or f'{session_date}T15:30:00+05:30',
        'source': source,
        'direction': item.get('direction') or 'BULLISH',
        'confidence': item.get('score'),
        'confidence_label': None,
        'reasoning': f"actual learning {item.get('category')}",
        'raw_payload': raw,
        'signal_stack': {
            'signal_type': item.get('category'),
            'prediction_horizon': 'intraday',
        },
    }


def _outcome_exists(prediction_id: str) -> bool:
    try:
        from backend.storage import market_memory_db as mmdb

        mmdb.init_market_memory_db()
        conn = mmdb.get_connection()
        try:
            row = conn.execute(
                'SELECT 1 FROM outcomes WHERE prediction_id = ? AND holding_period = ? LIMIT 1',
                (prediction_id, HOLDING_PERIOD),
            ).fetchone()
            return row is not None
        finally:
            conn.close()
    except Exception:
        return False


def _write_state(summary: dict[str, Any], *, state_path: Path | None = None) -> None:
    try:
        path = state_path or _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')
    except Exception:
        pass


def load_latest_actual_learning_summary(*, state_path: Path | None = None) -> dict[str, Any]:
    return _load_json(state_path or _state_path())


def _empty_summary(session_date: str) -> dict[str, Any]:
    return {
        'ok': True,
        'resolver': 'actual_learning',
        'version': RESOLVER_VERSION,
        'session_date': session_date,
        'started_at': _now_ist().isoformat(),
        'finished_at': '',
        'candidates': 0,
        'predictions_tracked': 0,
        'sample_updated': 0,
        'written': 0,
        'already_resolved': 0,
        'pending_data': 0,
        'pending_reasons': {},
        'price_evidence': {},
        'errors': 0,
        'watchlist': {'win': 0, 'loss': 0, 'neutral': 0},
        'avoid': {'success': 0, 'fail': 0, 'neutral': 0},
        'tradecard': {'resolved': 0, 'no_fill': 0},
        'missed_opportunities': 0,
        'latest_outcomes': [],
        'pending_items': [],
        'source_binding': {
            'sent_symbols': [],
            'resolved': 0,
            'pending_data': 0,
        },
        'market_memory': {
            'predictions_tracked': 0,
            'resolved_outcomes': 0,
            'pending_outcomes': 0,
            'hit_rate': None,
            'bullish_hit_rate': None,
            'avoid_rejection_hit_rate': None,
            'last_resolved_timestamp': None,
        },
        'explanation': {
            'best_signal_today': 'No resolved signal yet.',
            'worst_signal_today': 'No resolved loss signal yet.',
            'trust_tomorrow': 'Require fresh price and volume confirmation.',
            'reduce_tomorrow': 'Reduce stale or unresolved setups.',
        },
    }


def _record_bucket(summary: dict[str, Any], item: dict[str, Any], result: dict[str, Any]) -> None:
    category = str(item.get('category') or '')
    resolved_as = str(result.get('resolved_as') or '').upper()
    if category in ('top_watch', 'scanner_watch'):
        key = 'neutral'
        if resolved_as == WIN:
            key = 'win'
        elif resolved_as == LOSS:
            key = 'loss'
        summary['watchlist'][key] += 1
    elif category == 'avoid':
        if resolved_as == AVOID_SUCCESS:
            summary['avoid']['success'] += 1
        elif resolved_as == AVOID_FAIL:
            summary['avoid']['fail'] += 1
        else:
            summary['avoid']['neutral'] += 1
    elif category == 'tradecard':
        if resolved_as == NO_FILL:
            summary['tradecard']['no_fill'] += 1
        else:
            summary['tradecard']['resolved'] += 1
    elif category == 'missed':
        summary['missed_opportunities'] += 1


def _record_pending_reason(summary: dict[str, Any], reason: str) -> None:
    token = str(reason or 'pending_data')
    reasons = summary.setdefault('pending_reasons', {})
    if isinstance(reasons, dict):
        reasons[token] = int(reasons.get(token) or 0) + 1


def _counts_as_learning_sample(resolved_as: str) -> bool:
    token = str(resolved_as or '').upper()
    return token not in NON_WL_OUTCOMES


def _build_explanation(outcomes: list[dict[str, Any]]) -> dict[str, str]:
    def _displayable_score(row: dict[str, Any]) -> bool:
        if not isinstance(row.get('actual_move'), (int, float)):
            return False
        if str(row.get('resolved_as') or '').upper() == NEUTRAL and abs(float(row.get('actual_move') or 0)) <= 1e-9:
            return _has_independent_price_delta(row.get('price_evidence') if isinstance(row.get('price_evidence'), dict) else None)
        return True

    scored = [row for row in outcomes if _displayable_score(row)]
    best = max(scored, key=lambda r: float(r.get('actual_move') or 0), default=None)
    worst = min(scored, key=lambda r: float(r.get('actual_move') or 0), default=None)
    winners = [row for row in outcomes if str(row.get('resolved_as') or '').upper() in (WIN, AVOID_SUCCESS)]
    losers = [row for row in outcomes if str(row.get('resolved_as') or '').upper() in (LOSS, AVOID_FAIL)]
    return {
        'best_signal_today': (
            f"{best.get('ticker')} {best.get('resolved_as')} {float(best.get('actual_move') or 0):+.2f}%"
            if best else 'No resolved signal yet.'
        ),
        'worst_signal_today': (
            f"{worst.get('ticker')} {worst.get('resolved_as')} {float(worst.get('actual_move') or 0):+.2f}%"
            if worst else 'No resolved loss signal yet.'
        ),
        'trust_tomorrow': (
            f"Trust {winners[0].get('category')} setups with fresh price/volume confirmation."
            if winners else 'Trust only setups with fresh price and volume confirmation.'
        ),
        'reduce_tomorrow': (
            f"Reduce {losers[0].get('category')} patterns that failed today."
            if losers else 'Reduce stale or unresolved setups.'
        ),
    }


def _attach_market_memory_summary(summary: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        summary['market_memory'] = {
            'predictions_tracked': int(summary.get('candidates') or 0),
            'resolved_outcomes': len(summary.get('latest_outcomes') or []),
            'pending_outcomes': int(summary.get('pending_data') or 0),
            'hit_rate': None,
            'bullish_hit_rate': None,
            'avoid_rejection_hit_rate': None,
            'last_resolved_timestamp': summary.get('finished_at'),
        }
        return
    try:
        from backend.storage.outcome_resolver import get_canonical_outcome_stats

        stats = get_canonical_outcome_stats()
        summary['market_memory'] = {
            'predictions_tracked': int(stats.get('predictions_tracked') or 0),
            'resolved_outcomes': int(stats.get('resolved_total') or 0),
            'pending_outcomes': int(stats.get('pending_total') or 0),
            'hit_rate': stats.get('hit_rate'),
            'bullish_hit_rate': stats.get('bullish_hit_rate'),
            'avoid_rejection_hit_rate': stats.get('bearish_hit_rate'),
            'last_resolved_timestamp': stats.get('last_resolved_at'),
        }
    except Exception:
        summary['market_memory'] = {
            'predictions_tracked': int(summary.get('predictions_tracked') or 0),
            'resolved_outcomes': len(summary.get('latest_outcomes') or []),
            'pending_outcomes': int(summary.get('pending_data') or 0),
            'hit_rate': None,
            'bullish_hit_rate': None,
            'avoid_rejection_hit_rate': None,
            'last_resolved_timestamp': summary.get('finished_at'),
        }


def run_actual_learning_resolver(
    *,
    session_date: str | None = None,
    market_data: dict[str, Any] | None = None,
    market_mode: str | None = None,
    sources: dict[str, Any] | None = None,
    dry_run: bool = False,
    refresh_cache: bool = True,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve today's actual-learning samples. Idempotent per symbol/date/category."""
    from backend.storage import market_memory_db as mmdb

    day = session_date or _today()
    summary = _empty_summary(day)
    data = market_data if market_data is not None else load_latest_market_data()
    resolved_market_mode = _resolve_learning_market_mode(data if isinstance(data, dict) else None, market_mode=market_mode)
    summary['market_mode'] = resolved_market_mode
    candidates = _source_candidates(day, sources=sources)
    summary['candidates'] = len(candidates)
    sent_symbols = sorted({str(item.get('ticker') or '').upper() for item in candidates if item.get('ticker')})
    summary['source_binding']['sent_symbols'] = sent_symbols
    evidence_by_symbol = capture_eod_price_evidence(
        sent_symbols,
        session_date=day,
        market_data=data if isinstance(data, dict) else None,
    )
    evidence_context = capture_eod_price_context(data if isinstance(data, dict) else None)
    summary['price_evidence'] = {
        ticker: rows[:3]
        for ticker, rows in evidence_by_symbol.items()
        if rows
    }
    if not dry_run:
        mmdb.init_market_memory_db()

    for item in candidates:
        try:
            prediction = _prediction_payload(item, day)
            prediction_id = mmdb.make_canonical_prediction_id(prediction, source_hint=prediction.get('source'))
            prediction['prediction_id'] = prediction_id
            result = _classify_item(
                item,
                data,
                session_date=day,
                evidence_by_symbol=evidence_by_symbol,
                evidence_context=evidence_context,
                market_mode=resolved_market_mode,
            )
            if result.get('status') == 'pending_data':
                summary['pending_data'] += 1
                summary['source_binding']['pending_data'] = int(summary['source_binding'].get('pending_data') or 0) + 1
                _record_pending_reason(summary, str(result.get('reason') or 'pending_data'))
                summary['pending_items'].append({
                    'ticker': item.get('ticker'),
                    'category': item.get('category'),
                    'reason': result.get('reason'),
                })
                safe_print(
                    f"[EOD_PRICE_EVIDENCE] symbol={item.get('ticker')} source=- "
                    f"ref={item.get('signal_price')} close=- move=- "
                    f"status=pending reason={result.get('reason')}",
                    flush=True,
                )
                safe_print(
                    f"[PRICE_EVIDENCE_BRIDGE] symbol={item.get('ticker')} "
                    f"ref_source=- close_source=- status=pending reason={result.get('reason')}",
                    flush=True,
                )
                safe_print(
                    f"[LEARNING_PRICE_VALIDATION] symbol={item.get('ticker')} "
                    f"status=pending_data reason={result.get('reason')}",
                    flush=True,
                )
                if not dry_run:
                    mmdb.upsert_prediction(prediction)
                    summary['predictions_tracked'] += 1
                continue
            resolved_as = str(result.get('resolved_as') or '').upper()
            if not dry_run and _outcome_exists(prediction_id):
                summary['already_resolved'] += 1
                if _counts_as_learning_sample(resolved_as):
                    summary['sample_updated'] += 1
                _record_bucket(summary, item, result)
                summary['latest_outcomes'].append({
                    'ticker': item.get('ticker'),
                    'category': item.get('category'),
                    'resolved_as': resolved_as,
                    'actual_move': result.get('actual_move'),
                    'price_evidence': result.get('price_evidence'),
                })
                summary['source_binding']['resolved'] = int(summary['source_binding'].get('resolved') or 0) + 1
                ev = result.get('price_evidence') if isinstance(result.get('price_evidence'), dict) else {}
                safe_print(
                    f"[EOD_PRICE_EVIDENCE] symbol={item.get('ticker')} "
                    f"source={ev.get('close_source') or 'tradecard'} "
                    f"ref={ev.get('ref_price', item.get('signal_price'))} "
                    f"close={ev.get('close_price', '-')} move={result.get('actual_move')} "
                    "status=valid",
                    flush=True,
                )
                safe_print(
                    f"[PRICE_EVIDENCE_BRIDGE] symbol={item.get('ticker')} "
                    f"ref_source={ev.get('ref_source') or 'tradecard'} "
                    f"close_source={ev.get('close_source') or 'tradecard'} "
                    f"status=valid reason={ev.get('close_reason') or 'valid'}",
                    flush=True,
                )
                safe_print(
                    f"[LEARNING_PRICE_VALIDATION] symbol={item.get('ticker')} "
                    f"status=resolved reason={result.get('expiry_result')}",
                    flush=True,
                )
                continue
            outcome = {
                'prediction_id': prediction_id,
                'actual_move': result.get('actual_move'),
                'high': (result.get('price_evidence') or {}).get('high') if isinstance(result.get('price_evidence'), dict) else None,
                'low': (result.get('price_evidence') or {}).get('low') if isinstance(result.get('price_evidence'), dict) else None,
                'expiry_result': result.get('expiry_result'),
                'resolved_as': result.get('resolved_as'),
                'holding_period': HOLDING_PERIOD,
                'raw_payload': {
                    'source': 'actual_learning_resolver',
                    'resolver_version': RESOLVER_VERSION,
                    'category': item.get('category'),
                    'ticker': item.get('ticker'),
                    'session_date': day,
                    'signal_price': item.get('signal_price'),
                    'result': result,
                    'eod_price_evidence': result.get('price_evidence'),
                },
            }
            if not dry_run:
                pid = mmdb.upsert_prediction(prediction)
                if not pid:
                    summary['errors'] += 1
                    continue
                if not mmdb.upsert_outcome(outcome):
                    summary['errors'] += 1
                    continue
                summary['written'] += 1
                summary['predictions_tracked'] += 1
            if _counts_as_learning_sample(resolved_as):
                summary['sample_updated'] += 1
            _record_bucket(summary, item, result)
            summary['latest_outcomes'].append({
                'ticker': item.get('ticker'),
                'category': item.get('category'),
                'resolved_as': resolved_as,
                'actual_move': result.get('actual_move'),
                'price_evidence': result.get('price_evidence'),
            })
            summary['source_binding']['resolved'] = int(summary['source_binding'].get('resolved') or 0) + 1
            ev = result.get('price_evidence') if isinstance(result.get('price_evidence'), dict) else {}
            safe_print(
                f"[EOD_PRICE_EVIDENCE] symbol={item.get('ticker')} "
                f"source={ev.get('close_source') or 'tradecard'} "
                f"ref={ev.get('ref_price', item.get('signal_price'))} "
                f"close={ev.get('close_price', '-')} move={result.get('actual_move')} "
                "status=valid",
                flush=True,
            )
            safe_print(
                f"[PRICE_EVIDENCE_BRIDGE] symbol={item.get('ticker')} "
                f"ref_source={ev.get('ref_source') or 'tradecard'} "
                f"close_source={ev.get('close_source') or 'tradecard'} "
                f"status=valid reason={ev.get('close_reason') or 'valid'}",
                flush=True,
            )
            safe_print(
                f"[LEARNING_PRICE_VALIDATION] symbol={item.get('ticker')} "
                f"status=resolved reason={result.get('expiry_result')}",
                flush=True,
            )
        except Exception:
            summary['errors'] += 1

    summary['explanation'] = _build_explanation(summary['latest_outcomes'])
    summary['finished_at'] = _now_ist().isoformat()
    _attach_market_memory_summary(summary, dry_run=dry_run)
    if not dry_run:
        _write_state(summary, state_path=state_path)
        if refresh_cache and (summary['written'] > 0 or summary['pending_data'] > 0):
            refresh_memory_dashboard_cache()
    safe_print(
        f"[ACTUAL_LEARNING_RESOLVER] date={day} sample_updated={summary['sample_updated']} "
        f"watchlist={summary['watchlist']} avoid={summary['avoid']} "
        f"pending_data={summary['pending_data']} errors={summary['errors']}",
        flush=True,
    )
    safe_print(
        f"[LEARNING_SOURCE_BINDING] candidates={summary['candidates']} "
        f"sent_symbols={','.join(sent_symbols) if sent_symbols else '-'} "
        f"resolved={summary['source_binding'].get('resolved', 0)} "
        f"pending_data={summary['pending_data']}",
        flush=True,
    )
    reason_summary = ','.join(
        f'{key}:{val}' for key, val in sorted((summary.get('pending_reasons') or {}).items())
    ) or '-'
    safe_print(
        f"[LEARNING_PENDING_DATA] count={summary['pending_data']} reasons={reason_summary}",
        flush=True,
    )
    return summary


def format_actual_learning_close_lines(summary: dict[str, Any] | None = None) -> list[str]:
    data = summary if isinstance(summary, dict) else load_latest_actual_learning_summary()
    if not data:
        return ['Actual learning sample updated: 0']
    watch = data.get('watchlist') or {}
    avoid = data.get('avoid') or {}
    tradecard = data.get('tradecard') or {}
    explanation = data.get('explanation') or {}
    pending_reasons = data.get('pending_reasons') if isinstance(data.get('pending_reasons'), dict) else {}
    reason_text = ', '.join(f'{k} {v}' for k, v in sorted(pending_reasons.items())) or 'none'
    return [
        f"Actual learning sample updated: {int(data.get('sample_updated') or 0)}",
        (
            'Watchlist resolved: '
            f"{int(watch.get('win') or 0)}/{int(watch.get('loss') or 0)}/{int(watch.get('neutral') or 0)}"
        ),
        (
            'Avoid resolved: '
            f"success {int(avoid.get('success') or 0)} / fail {int(avoid.get('fail') or 0)}"
        ),
        f"Pending data: {int(data.get('pending_data') or 0)}",
        f"Pending data reasons: {reason_text}",
        (
            'Tradecard resolved/no-fill: '
            f"{int(tradecard.get('resolved') or 0)}/{int(tradecard.get('no_fill') or 0)}"
        ),
        f"Best signal today: {explanation.get('best_signal_today') or 'No resolved signal yet.'}",
        f"Worst signal today: {explanation.get('worst_signal_today') or 'No resolved loss signal yet.'}",
        f"What to trust tomorrow: {explanation.get('trust_tomorrow') or 'Fresh price + volume confirmation.'}",
        f"What to reduce tomorrow: {explanation.get('reduce_tomorrow') or 'Stale or unresolved setups.'}",
    ]
