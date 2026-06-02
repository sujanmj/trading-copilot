"""Append-only lifecycle audit trail."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

import pytz

from backend.utils.config import DATA_DIR, LOGS_DIR

IST = pytz.timezone('Asia/Kolkata')
AUDIT_FILE = LOGS_DIR / 'lifecycle_audit.log'
ARCHIVE_FILE = DATA_DIR / 'expired_predictions_archive.json'


def log_lifecycle_event(event: str, detail: str, *, payload: Optional[dict] = None) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        'at': datetime.now(IST).isoformat(),
        'event': event,
        'detail': detail,
        'payload': payload or {},
    }
    try:
        with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    except Exception:
        pass


def archive_expired_rows(rows: list) -> int:
    if not rows:
        return 0
    existing = {'entries': []}
    if ARCHIVE_FILE.exists():
        try:
            import json as _json
            existing = _json.loads(ARCHIVE_FILE.read_text(encoding='utf-8'))
        except Exception:
            existing = {'entries': []}
    entries = list(existing.get('entries') or [])
    entries.extend(rows)
    entries = entries[-5000:]
    from backend.storage.json_io import atomic_write_json
    atomic_write_json(ARCHIVE_FILE, {
        'updated_at': datetime.now(IST).isoformat(),
        'count': len(entries),
        'entries': entries,
    })
    log_lifecycle_event('archive_expired', f'archived {len(rows)} rows', payload={'total': len(entries)})
    return len(rows)
