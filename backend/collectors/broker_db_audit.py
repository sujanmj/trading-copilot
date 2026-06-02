"""
Broker predictions DB audit (Stage 39F).

Audit existing broker_predictions rows for write-safe eligibility.
Reuses broker_db_write_gate logic — no fake rows, no blind deletes.
"""

from __future__ import annotations

import json
from typing import Any

from backend.collectors.broker_db_write_gate import evaluate_broker_write_eligibility
from backend.storage.market_memory_db import get_connection, init_market_memory_db


def _parse_raw_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith('{'):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _row_title(row: dict[str, Any], raw: dict[str, Any]) -> str:
    for container in (raw, row):
        for key in ('headline', 'title', 'notes', 'reason', 'summary'):
            val = container.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()[:240]
    return ''


def _row_source_url(row: dict[str, Any], raw: dict[str, Any]) -> str:
    for container in (raw, row):
        for key in ('url', 'link', 'source_url'):
            val = container.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return ''


def _row_source_type(row: dict[str, Any], raw: dict[str, Any]) -> str:
    token = str(row.get('source_type') or raw.get('source_type') or '').strip()
    if token:
        return token
    collector = str(raw.get('collector_source') or row.get('collector_source') or '').strip().lower()
    if collector == 'manual':
        return 'manual'
    if collector == 'tv':
        return 'tv'
    if collector == 'angel':
        return 'broker'
    if raw.get('feed_name') or raw.get('link'):
        return 'rss'
    return 'news'


def db_row_to_gate_item(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a broker_predictions DB row into gate input shape."""
    raw = _parse_raw_payload(row.get('raw_payload'))
    title = _row_title(row, raw)
    return {
        'ticker': row.get('ticker'),
        'title': title,
        'headline': title,
        'source': row.get('broker_source'),
        'broker_source': row.get('broker_source'),
        'direction': row.get('bullish_or_bearish'),
        'stance': row.get('bullish_or_bearish'),
        'direction_confidence': raw.get('direction_confidence') or row.get('direction_confidence'),
        'classification': raw.get('classification') or row.get('classification') or 'broker_prediction_candidate',
        'classification_reason': raw.get('classification_reason') or row.get('classification_reason'),
        'direction_reason': raw.get('direction_reason') or row.get('direction_reason'),
        'source_type': _row_source_type(row, raw),
        'collector_source': raw.get('collector_source'),
        'raw_payload': raw,
        'dedupe_key': row.get('dedupe_key'),
        'prediction_date': raw.get('prediction_date') or str(row.get('created_at') or '')[:10],
    }


def _duplicate_key(row: dict[str, Any]) -> tuple[str, str, str]:
    raw = _parse_raw_payload(row.get('raw_payload'))
    title = _row_title(row, raw).lower()[:240]
    return (
        str(row.get('broker_source') or '').strip().lower(),
        str(row.get('ticker') or '').strip().upper(),
        title,
    )


def fetch_all_broker_prediction_rows() -> list[dict[str, Any]]:
    """Load all broker_predictions rows as plain dicts."""
    if not init_market_memory_db():
        return []
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, prediction_id, broker_source, ticker, bullish_or_bearish,
                   target_type, timeframe, confidence, raw_payload, dedupe_key, created_at
            FROM broker_predictions
            ORDER BY id ASC
            """,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def audit_broker_prediction_row(row: dict[str, Any], *, duplicate_ids: set[int] | None = None) -> dict[str, Any]:
    """Audit one broker_predictions row; returns safety verdict."""
    row_id = int(row.get('id') or 0)
    raw = _parse_raw_payload(row.get('raw_payload'))
    title = _row_title(row, raw)
    gate_item = db_row_to_gate_item(row)
    verdict = evaluate_broker_write_eligibility(gate_item)
    eligibility = str(verdict.get('eligibility') or 'reject')
    reasons = list(verdict.get('warnings') or [])
    if verdict.get('reason'):
        reasons.insert(0, str(verdict.get('reason')))

    is_duplicate = duplicate_ids is not None and row_id in duplicate_ids
    if is_duplicate and 'duplicate_in_broker_predictions' not in reasons:
        reasons.append('duplicate_in_broker_predictions')

    if is_duplicate:
        safety = 'unsafe'
        bucket = 'duplicate'
    elif eligibility == 'write_safe':
        safety = 'safe'
        bucket = 'safe'
    elif eligibility == 'review_only':
        safety = 'unsafe'
        bucket = 'review_only'
    else:
        safety = 'unsafe'
        bucket = 'reject'

    return {
        'id': row_id,
        'ticker': row.get('ticker'),
        'broker_source': row.get('broker_source'),
        'stance': row.get('bullish_or_bearish'),
        'title': title,
        'created_at': row.get('created_at'),
        'source_type': _row_source_type(row, raw),
        'source_url': _row_source_url(row, raw),
        'eligibility': eligibility,
        'safety': safety,
        'bucket': bucket,
        'reasons': reasons,
        'required_human_review': bool(verdict.get('required_human_review')),
    }


def _find_duplicate_row_ids(rows: list[dict[str, Any]]) -> set[int]:
    """Mark later rows unsafe when source+ticker+title duplicate."""
    seen: dict[tuple[str, str, str], int] = {}
    duplicate_ids: set[int] = set()
    for row in rows:
        row_id = int(row.get('id') or 0)
        key = _duplicate_key(row)
        if not key[2]:
            continue
        if key in seen:
            duplicate_ids.add(row_id)
        else:
            seen[key] = row_id
    return duplicate_ids


def audit_all_broker_predictions() -> dict[str, Any]:
    """Audit every broker_predictions row."""
    rows = fetch_all_broker_prediction_rows()
    duplicate_ids = _find_duplicate_row_ids(rows)
    audited: list[dict[str, Any]] = []
    counts = {'safe': 0, 'review_only': 0, 'unsafe': 0, 'duplicate': 0, 'reject': 0}

    for row in rows:
        result = audit_broker_prediction_row(row, duplicate_ids=duplicate_ids)
        audited.append(result)
        bucket = result.get('bucket') or 'unsafe'
        if bucket == 'safe':
            counts['safe'] += 1
        elif bucket == 'duplicate':
            counts['duplicate'] += 1
            counts['unsafe'] += 1
        elif bucket == 'review_only':
            counts['review_only'] += 1
            counts['unsafe'] += 1
        else:
            counts['reject'] += 1
            counts['unsafe'] += 1

    return {
        'ok': True,
        'total': len(rows),
        'counts': counts,
        'duplicate_ids': sorted(duplicate_ids),
        'rows': audited,
    }


def find_unsafe_broker_predictions() -> dict[str, Any]:
    """Return unsafe broker_predictions rows only."""
    audit = audit_all_broker_predictions()
    unsafe_rows = [
        row for row in audit.get('rows') or []
        if row.get('safety') == 'unsafe'
    ]
    return {
        'ok': True,
        'total': audit.get('total', 0),
        'unsafe_count': len(unsafe_rows),
        'counts': audit.get('counts') or {},
        'unsafe_rows': unsafe_rows,
    }
