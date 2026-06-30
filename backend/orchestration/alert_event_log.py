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
    'EMERGENCY_MACRO_ALERT': 'emergency_macro',
    'MARKET_CLOSE_SUMMARY': 'close',
    'MIDDAY_UPDATE': 'intraday',
    'OUTCOME_REPORT': 'today',
    'TODAY_DECISION': 'today',
    'TOMORROW_DECISION': 'tomorrow',
}


def _log(msg: str) -> None:
    print(f'[ALERT_EVENT_LOG] {msg}', flush=True)


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
) -> dict:
    """Append one alert event line. Returns the logged entry."""
    if isinstance(tickers, str):
        ticker_list = [tickers] if tickers else []
    else:
        ticker_list = [str(t).upper() for t in (tickers or []) if t]

    ts = timestamp or datetime.now(IST).isoformat()
    entry = {
        'timestamp': ts,
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
                trading_date=ts[:10] if len(ts) >= 10 else None,
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
            day = ts[:10] if len(ts) >= 10 else ''
            if day == review_date:
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
        'rows': rows,
    }
