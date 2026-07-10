"""
Persistent Telegram alert event log (Stage 46I).

Appends one JSON line per sent alert under get_data_path()/alert_event_log.jsonl.
EOD review reads this file for alerts_sent / scorable / pending counts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')
ALERT_LOG_FILE = get_data_path('alert_event_log.jsonl')

SCORABLE_ALERT_TYPES = frozenset({
    'premarket',
    'open',
    'intraday',
    'emergency_macro',
    'today',
    'tomorrow',
    'close',
})

CATEGORY_TO_ALERT_TYPE = {
    'PRE_MARKET': 'premarket',
    'INTRADAY_OPPORTUNITY': 'open',
    'INTRADAY_EVENT': 'intraday',
    'OPENING_RADAR_ARMED': 'open',
    'OPENING_RALLY_RADAR': 'open',
    'EARLY_TRADECARD_PROVISIONAL': 'open',
    'FINAL_OPENING_CONFIRMATION': 'open',
    'EMERGENCY_MACRO_ALERT': 'emergency_macro',
    'MARKET_CLOSE_SUMMARY': 'close',
    'MIDDAY_UPDATE': 'intraday',
    'OUTCOME_REPORT': 'today',
    'TODAY_DECISION': 'today',
    'TOMORROW_DECISION': 'tomorrow',
}


def _log(msg: str) -> None:
    print(f'[ALERT_EVENT_LOG] {msg}', flush=True)


def _session_date_from_timestamp(ts: str) -> str:
    """Derive IST trading session date from an ISO timestamp."""
    text = str(ts or '').strip()
    if not text:
        return ''
    try:
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else ''


def _row_session_date(row: dict[str, Any]) -> str:
    explicit = str(row.get('session_date') or '').strip()
    if explicit:
        return explicit
    return _session_date_from_timestamp(str(row.get('timestamp') or ''))


def _intraday_dedup_key(row: dict[str, Any]) -> str:
    tickers = sorted(str(t).upper() for t in (row.get('tickers') or []) if t)
    return '|'.join([
        _row_session_date(row),
        str(row.get('alert_type') or '').lower(),
        ','.join(tickers),
        str(row.get('reason_hash') or ''),
    ])


def count_individual_intraday_alerts(review_date: str) -> int:
    """Count unique intraday alert events for a session date (not batch wrappers)."""
    seen: set[str] = set()
    count = 0
    for row in read_alert_events_for_date(review_date):
        if not isinstance(row, dict):
            continue
        meta = row.get('metadata') if isinstance(row.get('metadata'), dict) else {}
        alert_type = str(row.get('alert_type') or '').lower()
        if alert_type != 'intraday' and not meta.get('intraday_batch_member'):
            continue
        if meta.get('intraday_batch_wrapper'):
            continue
        key = _intraday_dedup_key(row)
        if key in seen:
            continue
        seen.add(key)
        count += 1
    return count


def reason_hash(text: str) -> str:
    norm = str(text or '').strip().lower()[:500]
    return hashlib.sha256(norm.encode('utf-8')).hexdigest()[:16]


def category_to_alert_type(category: str) -> str:
    return CATEGORY_TO_ALERT_TYPE.get(str(category or '').upper(), 'intraday')


def log_alert_event(
    *,
    category: str,
    tickers: Optional[list[str] | str] = None,
    direction: str = 'NEUTRAL',
    score: Optional[float] = None,
    price_at_alert: Optional[float] = None,
    volume_at_alert: Optional[float] = None,
    reason: str = '',
    timestamp: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict:
    """Append one alert event line. Returns the logged entry."""
    if isinstance(tickers, str):
        ticker_list = [tickers] if tickers else []
    else:
        ticker_list = [str(t).upper() for t in (tickers or []) if t]

    ts = timestamp or datetime.now(IST).isoformat()
    session_date = _session_date_from_timestamp(ts)
    entry = {
        'timestamp': ts,
        'session_date': session_date,
        'alert_type': category_to_alert_type(category),
        'category': str(category or ''),
        'tickers': ticker_list,
        'direction': str(direction or 'NEUTRAL').upper(),
        'score': round(float(score), 3) if score is not None else None,
        'confidence': round(float(score), 3) if score is not None else None,
        'price_at_alert': price_at_alert,
        'volume_at_alert': volume_at_alert,
        'reason_hash': reason_hash(reason or category),
        'reason_preview': str(reason or '')[:120],
    }
    if metadata:
        entry['metadata'] = dict(metadata)
    try:
        ALERT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with ALERT_LOG_FILE.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError as exc:
        _log(f'write failed: {exc}')
    try:
        from backend.analytics.actual_learning_resolver import record_learning_candidate

        for ticker in ticker_list:
            record_learning_candidate(
                symbol=ticker,
                emitted_at=ts,
                trading_date=session_date or (ts[:10] if len(ts) >= 10 else None),
                source=f"alert_event:{entry['alert_type']}",
                reference_price=price_at_alert,
                reference_price_source='alert_event_log.price_at_alert' if price_at_alert else '',
                scanner_timestamp=ts,
                volume=volume_at_alert,
                direction=entry['direction'],
                score=entry['score'],
                category='scanner_watch' if entry['alert_type'] in ('open', 'intraday') else 'top_watch',
                raw=entry,
            )
    except Exception:
        pass
    return entry


def log_intraday_batch_ticker_events(
    events: list[dict[str, Any]],
    *,
    regime: str = '',
    timestamp: str | None = None,
) -> list[dict]:
    """Log one intraday alert event per ticker in a batch (accounting, not message grouping)."""
    logged: list[dict] = []
    ts = timestamp or datetime.now(IST).isoformat()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ticker = str(ev.get('ticker') or '').strip().upper()
        if not ticker:
            continue
        signal = ev.get('signal') if isinstance(ev.get('signal'), dict) else {}
        price = None
        volume = None
        for source in (signal, ev):
            try:
                price_val = float(source.get('price') or source.get('last_price') or 0)
            except (TypeError, ValueError):
                price_val = 0.0
            if price_val > 0:
                price = price_val
            try:
                vol_val = float(source.get('volume_ratio') or source.get('volume') or 0)
            except (TypeError, ValueError):
                vol_val = 0.0
            if vol_val > 0:
                volume = vol_val
        detail = str(ev.get('detail') or ev.get('change_detail') or ev.get('type') or '')[:120]
        logged.append(
            log_alert_event(
                category='INTRADAY_EVENT',
                tickers=ticker,
                direction=str(ev.get('direction') or signal.get('direction') or 'BULLISH').upper(),
                score=float(ev.get('confidence') or signal.get('confidence') or 0) or None,
                price_at_alert=price,
                volume_at_alert=volume,
                reason=detail or f'intraday batch {regime}'.strip(),
                timestamp=ts,
                metadata={
                    'intraday_batch_member': True,
                    'batch_regime': str(regime or ''),
                    'event_type': str(ev.get('type') or ''),
                },
            )
        )
    return logged


def summarize_opening_workflow_for_date(review_date: str) -> dict:
    """Return compact counts for the scheduled opening workflow."""
    rows = [
        row for row in read_alert_events_for_date(review_date)
        if isinstance(row.get('metadata'), dict)
        and row.get('metadata', {}).get('opening_workflow')
    ]
    stage_symbols: dict[str, set[str]] = {
        '0900': set(),
        '0920': set(),
        '0925': set(),
        '0931': set(),
    }
    best_by_stage: dict[str, str] = {}
    for row in rows:
        meta = row.get('metadata') or {}
        stage = str(meta.get('opening_stage') or '').strip()
        if stage not in stage_symbols:
            continue
        for ticker in row.get('tickers') or []:
            sym = str(ticker or '').strip().upper()
            if sym:
                stage_symbols[stage].add(sym)
                if meta.get('opening_best'):
                    best_by_stage[stage] = sym
    captured = sorted(set().union(*stage_symbols.values())) if stage_symbols else []
    try:
        from backend.trading.candidate_outcome_learning import eligible_learning_symbols

        eligible = eligible_learning_symbols(review_date)
        if eligible:
            captured = eligible
        else:
            captured = []
    except Exception:
        pass
    try:
        from backend.trading.opening_workflow_accounting import summarize_opening_workflow_accounting

        accounting = summarize_opening_workflow_accounting(review_date)
    except Exception:
        accounting = {}
    return {
        'radar_armed': len(stage_symbols['0900']),
        'opening_radar': len(stage_symbols['0920']),
        'early_tradecard_best': accounting.get('early_tradecard_best') or best_by_stage.get('0925', ''),
        'final_confirmation_best': accounting.get('final_confirmation_best') or best_by_stage.get('0931', ''),
        'early_tradecards_generated': int(accounting.get('early_tradecards_generated') or 0),
        'final_confirmation_generated': int(accounting.get('final_confirmation_generated') or 0),
        'final_confirmation_state': str(accounting.get('final_confirmation_state') or ''),
        'confirmed': int(accounting.get('confirmed') or 0),
        'rejected': int(accounting.get('rejected') or 0),
        'wait_pullback': int(accounting.get('wait_pullback') or 0),
        'pullback_only': int(accounting.get('pullback_only') or 0),
        'chase_risk': int(accounting.get('chase_risk') or 0),
        'learning_candidates': captured,
        'rows': rows,
    }


def read_alert_events_for_date(review_date: str) -> list[dict]:
    """Return alert log entries whose timestamp date matches review_date (IST)."""
    if not ALERT_LOG_FILE.is_file():
        return []
    rows: list[dict] = []
    try:
        for line in ALERT_LOG_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            ts = str(row.get('timestamp') or '')
            if _row_session_date(row) == review_date:
                rows.append(row)
    except OSError as exc:
        _log(f'read failed: {exc}')
    return rows


def summarize_alert_events_for_date(review_date: str) -> dict:
    """Summarize today's logged alerts for EOD display."""
    rows = read_alert_events_for_date(review_date)
    scorable = [r for r in rows if r.get('alert_type') in SCORABLE_ALERT_TYPES]
    return {
        'alerts_sent': len(rows),
        'alerts_tracked': len(rows),
        'alerts_scorable': len(scorable),
        'alerts_pending_score': len(scorable),
        'intraday_alert_count': count_individual_intraday_alerts(review_date),
        'rows': rows,
    }
