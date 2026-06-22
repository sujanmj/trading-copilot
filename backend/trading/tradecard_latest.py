"""
Per-chat latest tradecard snapshot — Stage 50Z addendum.

/tradecard explain must explain the same card as the last /tradecard, not re-select.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.storage.market_memory_outcomes import load_latest_market_data, lookup_latest_price
from backend.utils.config import DATA_DIR

IST = __import__('zoneinfo').ZoneInfo('Asia/Kolkata')

LATEST_FILE = DATA_DIR / 'tradecard_latest_by_chat.json'

NO_LATEST_MESSAGE = 'No active/latest tradecard found. Run /tradecard first.'

AUDIT_ONLY_STATUSES = frozenset({
    'NO_ACTIVE_ENTRY',
    'NEXT_SESSION_WATCH',
    'ENTRY_MISSED',
})


def _today() -> str:
    return datetime.now(IST).strftime('%Y-%m-%d')


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _load_store() -> dict[str, Any]:
    if not LATEST_FILE.is_file():
        return {}
    try:
        parsed = json.loads(LATEST_FILE.read_text(encoding='utf-8'))
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_store(store: dict[str, Any]) -> None:
    LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    LATEST_FILE.write_text(json.dumps(store, indent=2), encoding='utf-8')


def save_latest_tradecard(
    chat_id: str | None,
    card: dict[str, Any],
    *,
    ticker: str,
    status: str,
    audit_only: bool = False,
) -> dict[str, Any]:
    """Persist the card shown by the last /tradecard for this chat."""
    sym = str(ticker or card.get('ticker') or '').strip().upper()
    if not sym or not isinstance(card, dict):
        return {}
    normalized_status = str(status or card.get('status') or '').strip().upper()
    audit = bool(audit_only or normalized_status in AUDIT_ONLY_STATUSES)
    cid = str(chat_id or 'default')
    record = {
        'chat_id': cid,
        'saved_at': _now_iso(),
        'session_date': _today(),
        'ticker': sym,
        'status': normalized_status,
        'audit_only': audit,
        'record_type': 'latest_tradecard_audit' if audit else 'latest_tradecard_active',
        'card': dict(card),
    }
    store = _load_store()
    store[cid] = record
    _write_store(store)
    return record


def load_latest_tradecard(chat_id: str | None) -> dict[str, Any] | None:
    cid = str(chat_id or 'default')
    record = _load_store().get(cid)
    return record if isinstance(record, dict) else None


def is_latest_tradecard_expired(record: dict[str, Any] | None) -> bool:
    if not isinstance(record, dict):
        return True
    return str(record.get('session_date') or '') != _today()


def is_tradecard_audit_status(status: object) -> bool:
    return str(status or '').strip().upper() in AUDIT_ONLY_STATUSES


def iter_latest_tradecards(*, session_date: str | None = None) -> list[dict[str, Any]]:
    day = session_date or _today()
    rows: list[dict[str, Any]] = []
    for record in _load_store().values():
        if not isinstance(record, dict):
            continue
        if str(record.get('session_date') or '') != day:
            continue
        rows.append(record)
    rows.sort(key=lambda row: str(row.get('saved_at') or ''), reverse=True)
    return rows


def find_latest_tradecard_audit(
    *,
    ticker: str | None = None,
    session_date: str | None = None,
) -> dict[str, Any] | None:
    sym = str(ticker or '').strip().upper()
    for record in iter_latest_tradecards(session_date=session_date):
        status = record.get('status')
        if not (record.get('audit_only') or is_tradecard_audit_status(status)):
            continue
        if sym and str(record.get('ticker') or '').strip().upper() != sym:
            continue
        return record
    return None


def summarize_latest_tradecard_audits(*, session_date: str | None = None) -> dict[str, Any]:
    rows = [
        row
        for row in iter_latest_tradecards(session_date=session_date)
        if row.get('audit_only') or is_tradecard_audit_status(row.get('status'))
    ]
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get('status') or '').strip().upper() or 'UNKNOWN'
        counts[status] = counts.get(status, 0) + 1
    return {
        'date': session_date or _today(),
        'count': len(rows),
        'counts': counts,
        'rows': rows,
    }


def refresh_pinned_card_price(card: dict[str, Any], ticker: str) -> dict[str, Any]:
    """Return card copy with current_price updated from live quotes only."""
    updated = dict(card)
    sym = str(ticker or updated.get('ticker') or '').strip().upper()
    if not sym:
        return updated
    market = load_latest_market_data()
    live = lookup_latest_price(market, sym) if market else None
    if live is not None:
        updated['current_price'] = round(live, 2)
    return updated


def reset_latest_tradecard_state() -> None:
    """Test helper — clear persisted latest cards."""
    if LATEST_FILE.is_file():
        LATEST_FILE.unlink()
