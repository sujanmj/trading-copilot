"""Durable Telegram alert suppression observability."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')
LOG_FILE = get_data_path('alert_suppression_log.jsonl')

_DUPLICATE_REASONS = {
    'duplicate',
    'dedupe',
    'duplicate_premarket',
    'no_meaningful_delta',
    'same_top3_no_delta',
}


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _append(entry: dict[str, Any]) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, separators=(',', ':')) + '\n')
    except Exception:
        pass


def log_suppression(
    *,
    reason: str,
    category: str = '',
    ticker: str = '',
    detail: str = '',
    stage: str = '',
    extra: dict[str, Any] | None = None,
) -> None:
    _append({
        'type': 'suppressed',
        'time': datetime.now(IST).isoformat(),
        'date': _today(),
        'category': str(category or ''),
        'ticker': str(ticker or '').upper(),
        'reason': str(reason or 'unknown')[:120],
        'detail': str(detail or '')[:300],
        'stage': str(stage or '')[:80],
        'extra': extra or {},
    })


def log_alert_sent(
    *,
    category: str,
    ticker: str = '',
    detail: str = '',
    confidence: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    _append({
        'type': 'sent',
        'time': datetime.now(IST).isoformat(),
        'date': _today(),
        'category': str(category or ''),
        'ticker': str(ticker or '').upper(),
        'detail': str(detail or '')[:300],
        'confidence': confidence,
        'extra': extra or {},
    })


def log_dispatch_debug(*, category: str = '', reason: str = '', detail: str = '', **extra: Any) -> None:
    _append({
        'type': 'debug',
        'time': datetime.now(IST).isoformat(),
        'date': _today(),
        'category': str(category or ''),
        'reason': str(reason or '')[:120],
        'detail': str(detail or '')[:300],
        'extra': extra,
    })


def _iter_entries(limit: int = 500) -> list[dict[str, Any]]:
    if not LOG_FILE.is_file():
        return []
    try:
        lines = LOG_FILE.read_text(encoding='utf-8').splitlines()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-max(1, int(limit)):]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def suppression_summary(*, limit: int = 100) -> dict[str, Any]:
    today = _today()
    entries = [row for row in _iter_entries(max(limit, 500)) if row.get('date') == today]
    suppressed = [row for row in entries if row.get('type') == 'suppressed']
    sent = [row for row in entries if row.get('type') == 'sent']
    reasons = Counter(str(row.get('reason') or 'unknown') for row in suppressed)
    duplicate_count = sum(
        1
        for row in suppressed
        if str(row.get('reason') or '').lower() in _DUPLICATE_REASONS
        or 'duplicate' in str(row.get('reason') or '').lower()
        or 'delta' in str(row.get('reason') or '').lower()
    )
    last = suppressed[-1] if suppressed else {}
    return {
        'date': today,
        'suppression_count': len(suppressed),
        'sent_count': len(sent),
        'by_reason': dict(reasons),
        'last_reason': last.get('reason') or '',
        'last_detail': last.get('detail') or '',
        'duplicate_alerts_avoided': duplicate_count,
        'ai_calls_avoided': len(suppressed),
        'recent_suppressed': suppressed[-8:],
        'recent_sent': sent[-8:],
        'path': str(LOG_FILE),
    }
