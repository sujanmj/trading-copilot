"""
My Feed SQLite store — text-only market lines (Stage 50A).

Never stores image paths or binary screenshot data.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.storage.data_paths import get_data_path

MY_FEED_DB_NAME = 'my_feed.db'

SCHEMA = """
CREATE TABLE IF NOT EXISTS feed_items (
    feed_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    raw_market_text TEXT,
    cleaned_summary TEXT,
    detected_source_app TEXT,
    tickers TEXT,
    sectors TEXT,
    themes TEXT,
    event_type TEXT,
    sentiment TEXT,
    impact_score REAL,
    urgency TEXT,
    suggested_action TEXT,
    confirmation_required INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    payload TEXT
);

CREATE INDEX IF NOT EXISTS idx_my_feed_created ON feed_items(created_at);
CREATE INDEX IF NOT EXISTS idx_my_feed_status ON feed_items(status);
CREATE INDEX IF NOT EXISTS idx_my_feed_source ON feed_items(source);
"""


def get_my_feed_db_path():
    return get_data_path(MY_FEED_DB_NAME)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    path = get_my_feed_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_my_feed_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _json_load(value: object) -> Any:
    if value in (None, ''):
        return []
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = _json_load(row['payload']) if row['payload'] else {}
    item = {
        'feed_id': row['feed_id'],
        'created_at': row['created_at'],
        'source': row['source'],
        'raw_market_text': row['raw_market_text'] or '',
        'cleaned_summary': row['cleaned_summary'] or '',
        'detected_source_app': row['detected_source_app'] or '',
        'tickers': _json_load(row['tickers']),
        'sectors': _json_load(row['sectors']),
        'themes': _json_load(row['themes']),
        'event_type': row['event_type'] or '',
        'sentiment': row['sentiment'] or '',
        'impact_score': float(row['impact_score'] or 0),
        'urgency': row['urgency'] or '',
        'suggested_action': row['suggested_action'] or '',
        'confirmation_required': bool(row['confirmation_required']),
        'status': row['status'] or 'active',
    }
    if isinstance(payload, dict):
        for key, val in payload.items():
            if key not in item and key != 'image_path':
                item[key] = val
    return item


def insert_feed_item(record: dict[str, Any]) -> dict[str, Any]:
    init_my_feed_db()
    feed_id = str(record.get('feed_id') or uuid.uuid4().hex[:12])
    created_at = str(record.get('created_at') or _now_iso())
    payload = dict(record.get('payload') or {})
    payload.pop('image_path', None)

    row = {
        'feed_id': feed_id,
        'created_at': created_at,
        'source': str(record.get('source') or 'gui_text'),
        'raw_market_text': str(record.get('raw_market_text') or ''),
        'cleaned_summary': str(record.get('cleaned_summary') or ''),
        'detected_source_app': str(record.get('detected_source_app') or ''),
        'tickers': _json_dump(record.get('tickers') or []),
        'sectors': _json_dump(record.get('sectors') or []),
        'themes': _json_dump(record.get('themes') or []),
        'event_type': str(record.get('event_type') or ''),
        'sentiment': str(record.get('sentiment') or ''),
        'impact_score': float(record.get('impact_score') or 0),
        'urgency': str(record.get('urgency') or ''),
        'suggested_action': str(record.get('suggested_action') or ''),
        'confirmation_required': 1 if record.get('confirmation_required') else 0,
        'status': str(record.get('status') or 'active'),
        'payload': _json_dump(payload),
    }

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO feed_items (
                feed_id, created_at, source, raw_market_text, cleaned_summary,
                detected_source_app, tickers, sectors, themes, event_type, sentiment,
                impact_score, urgency, suggested_action, confirmation_required, status, payload
            ) VALUES (
                :feed_id, :created_at, :source, :raw_market_text, :cleaned_summary,
                :detected_source_app, :tickers, :sectors, :themes, :event_type, :sentiment,
                :impact_score, :urgency, :suggested_action, :confirmation_required, :status, :payload
            )
            """,
            row,
        )
        conn.commit()
    return row_to_dict_from_record(feed_id, row)


def row_to_dict_from_record(feed_id: str, row: dict[str, Any]) -> dict[str, Any]:
    payload = _json_load(row.get('payload')) if row.get('payload') else {}
    item = {
        'feed_id': feed_id,
        'created_at': row['created_at'],
        'source': row['source'],
        'raw_market_text': row['raw_market_text'],
        'cleaned_summary': row['cleaned_summary'],
        'detected_source_app': row['detected_source_app'],
        'tickers': _json_load(row['tickers']),
        'sectors': _json_load(row['sectors']),
        'themes': _json_load(row['themes']),
        'event_type': row['event_type'],
        'sentiment': row['sentiment'],
        'impact_score': float(row['impact_score'] or 0),
        'urgency': row['urgency'],
        'suggested_action': row['suggested_action'],
        'confirmation_required': bool(row['confirmation_required']),
        'status': row['status'],
    }
    if isinstance(payload, dict):
        for key, val in payload.items():
            if key not in item and key != 'image_path':
                item[key] = val
    return item


def list_items(
    *,
    limit: int = 20,
    today_only: bool = False,
    status: str | None = 'active',
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    init_my_feed_db()
    clauses = []
    params: list[Any] = []
    if include_archived and status is None:
        clauses.append("status IN ('active', 'archived')")
    elif include_archived and status == 'archived':
        clauses.append("status = 'archived'")
    elif status:
        clauses.append('status = ?')
        params.append(status)
    if today_only:
        today_prefix = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        clauses.append('created_at LIKE ?')
        params.append(f'{today_prefix}%')
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    sql = f'SELECT * FROM feed_items {where} ORDER BY created_at DESC, rowid DESC LIMIT ?'
    params.append(max(1, int(limit)))
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row_to_dict(r) for r in rows]


def get_item(feed_id: str) -> dict[str, Any] | None:
    init_my_feed_db()
    with _connect() as conn:
        row = conn.execute('SELECT * FROM feed_items WHERE feed_id = ?', (feed_id,)).fetchone()
    return row_to_dict(row) if row else None


def archive_item(feed_id: str, *, reason: str = '') -> bool:
    init_my_feed_db()
    with _connect() as conn:
        row = conn.execute('SELECT payload FROM feed_items WHERE feed_id = ?', (feed_id,)).fetchone()
        if not row:
            return False
        payload = _json_load(row['payload']) if row['payload'] else {}
        if not isinstance(payload, dict):
            payload = {}
        if reason:
            payload['archive_reason'] = reason
        payload['archived'] = True
        cur = conn.execute(
            "UPDATE feed_items SET status = 'archived', payload = ? WHERE feed_id = ? AND status != 'archived'",
            (_json_dump(payload), feed_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_feed_item_metadata(feed_id: str, fields: dict[str, Any]) -> bool:
    init_my_feed_db()
    allowed = {
        'tickers', 'sectors', 'themes', 'event_type', 'sentiment', 'impact_score',
        'urgency', 'suggested_action', 'confirmation_required', 'detected_source_app',
    }
    patch: dict[str, Any] = {}
    for key, value in (fields or {}).items():
        if key not in allowed:
            continue
        if key in {'tickers', 'sectors', 'themes'}:
            patch[key] = _json_dump(value)
        elif key == 'confirmation_required':
            patch[key] = 1 if value else 0
        elif key == 'impact_score':
            patch[key] = float(value or 0)
        else:
            patch[key] = value
    if not patch:
        return False
    set_clause = ', '.join(f'{key} = ?' for key in patch)
    params = list(patch.values()) + [feed_id]
    with _connect() as conn:
        cur = conn.execute(
            f'UPDATE feed_items SET {set_clause} WHERE feed_id = ?',
            params,
        )
        conn.commit()
        return cur.rowcount > 0


def find_recent_duplicate(cleaned_summary: str, *, hours: int = 6) -> dict[str, Any] | None:
    text = str(cleaned_summary or '').strip().lower()
    if not text:
        return None
    init_my_feed_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM feed_items WHERE status = 'active' ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    for row in rows:
        existing = str(row['cleaned_summary'] or '').strip().lower()
        if existing == text:
            return row_to_dict(row)
    return None


def active_items_for_tickers(tickers: list[str], *, limit: int = 30) -> list[dict[str, Any]]:
    wanted = {str(t).upper() for t in tickers if t}
    if not wanted:
        return []
    items = list_items(limit=limit, status='active')
    matched: list[dict[str, Any]] = []
    for item in items:
        item_tickers = {str(t).upper() for t in (item.get('tickers') or [])}
        if item_tickers & wanted:
            matched.append(item)
    return matched
