"""
Shared Telegram / budget cache freshness — Stage 48K / 48Q.

/status, /budget, /aihub scan, and decision surfaces share the same 90 min threshold.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')

BUDGET_CACHE_FRESH_THRESHOLD_MINUTES = 90


def classify_budget_cache_freshness(age_minutes: int | None) -> str:
    """Return fresh | stale | cache_missing for budget/theme cache rows."""
    if age_minutes is None or age_minutes < 0:
        return 'cache_missing'
    if age_minutes <= BUDGET_CACHE_FRESH_THRESHOLD_MINUTES:
        return 'fresh'
    return 'stale'


def budget_cache_freshness_from_age_hours(age_h: float | None) -> str:
    if age_h is None:
        return 'cache_missing'
    age_min = int(age_h * 60)
    return classify_budget_cache_freshness(age_min)


def parse_feed_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def compute_feed_age_minutes(
    path: Path,
    *,
    timestamp_key: str = '',
) -> tuple[int, str]:
    """Return (age_minutes, timestamp_text) for a local data file."""
    from backend.telegram.response_format import file_timestamp_iso

    ts_txt = '—'
    age_min = -1
    if not path.is_file():
        return age_min, ts_txt
    try:
        age_sec = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
        age_min = max(0, int(age_sec // 60))
    except OSError:
        age_min = -1
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(payload, dict):
            embedded = (
                payload.get(timestamp_key)
                or payload.get('generated_at')
                or payload.get('cache_refreshed_at')
                or payload.get('refreshed_at')
                or payload.get('updated_at')
                or payload.get('timestamp')
                or payload.get('last_updated')
            )
            if embedded:
                ts_txt = str(embedded)
                parsed = parse_feed_timestamp(embedded)
                if parsed is not None:
                    age_min = max(
                        0,
                        int((datetime.now(timezone.utc) - parsed).total_seconds() // 60),
                    )
    except Exception:
        pass
    if ts_txt == '—':
        file_ts = file_timestamp_iso(path)
        if file_ts:
            ts_txt = file_ts
    return age_min, ts_txt


def format_age_short(age_minutes: int) -> str:
    if age_minutes < 0:
        return '—'
    if age_minutes < 60:
        return f'{age_minutes}m'
    return f'{age_minutes // 60}h'


def format_compact_freshness_line(name: str, age_minutes: int) -> str:
    """Compact label — e.g. Scanner: fresh · 2m / Report: stale · 11h."""
    if age_minutes < 0:
        return f'{name}: unavailable'
    status = classify_budget_cache_freshness(age_minutes)
    return f'{name}: {status} · {format_age_short(age_minutes)}'


def scanner_cache_age_minutes() -> int:
    from backend.storage.data_paths import get_data_path

    age_min, _ = compute_feed_age_minutes(get_data_path('scanner_data.json'))
    return age_min


def format_budget_feed_freshness_line(label: str, path: Path, *, timestamp_key: str = '') -> str:
    """Format Latest <label>: timestamp · age <x> · fresh|stale|cache_missing."""
    age_min, ts_txt = compute_feed_age_minutes(path, timestamp_key=timestamp_key)
    if age_min < 0:
        return f'{label}: unavailable'
    age_txt = format_age_short(age_min)
    freshness = classify_budget_cache_freshness(age_min)
    short_name = str(label).replace('Latest ', '').strip()
    return f'{short_name}: {freshness} · {age_txt}'
