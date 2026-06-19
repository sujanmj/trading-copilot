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
) -> dict[str, Any]:
    """Persist the card shown by the last /tradecard for this chat."""
    sym = str(ticker or card.get('ticker') or '').strip().upper()
    if not sym or not isinstance(card, dict):
        return {}
    cid = str(chat_id or 'default')
    record = {
        'chat_id': cid,
        'saved_at': _now_iso(),
        'session_date': _today(),
        'ticker': sym,
        'status': str(status or card.get('status') or '').strip().upper(),
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
