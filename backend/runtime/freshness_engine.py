"""
Freshness engine — normalize timestamps, safe age formatting, IST authority.

Prevents None propagation and invalid display strings like "Nonem" / "nullm".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pytz

IST = pytz.timezone('Asia/Kolkata')
FRESHNESS_UNAVAILABLE = 'freshness unavailable'

# Phase-3 tiers: <5m healthy, 5-15m aging, 15m+ stale
HEALTHY_MAX_MINUTES = 5
AGING_MAX_MINUTES = 15
STALE_MIN_MINUTES = 15


def freshness_health_tier(age: Any) -> str:
    """Return healthy | aging | stale | unavailable."""
    if age is None:
        return 'unavailable'
    try:
        n = int(age)
    except (TypeError, ValueError):
        return 'unavailable'
    if n < 0:
        return 'unavailable'
    if n < HEALTHY_MAX_MINUTES:
        return 'healthy'
    if n < AGING_MAX_MINUTES:
        return 'aging'
    return 'stale'


def is_snapshot_stale(age: Any) -> bool:
    tier = freshness_health_tier(age)
    return tier == 'stale'


def normalize_timestamp(value: Any) -> Optional[datetime]:
    """Parse assorted timestamp shapes into timezone-aware IST datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(value), tz=IST)
            return dt.astimezone(IST)
        except (OSError, OverflowError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text or text.lower() in ('none', 'null', 'nan', 'undefined'):
            return None
        try:
            if 'T' in text:
                dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
            else:
                dt = datetime.strptime(text[:19], '%Y-%m-%d %H:%M:%S')
                dt = IST.localize(dt)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = IST.localize(dt)
    return dt.astimezone(IST)


def age_minutes(value: Any, *, now: Optional[datetime] = None) -> Optional[int]:
    """Age in whole minutes; None when timestamp invalid."""
    dt = normalize_timestamp(value)
    if dt is None:
        return None
    ref = now or datetime.now(IST)
    if ref.tzinfo is None:
        ref = IST.localize(ref)
    ref = ref.astimezone(IST)
    if dt > ref:
        return None
    return max(0, int((ref - dt).total_seconds() / 60))


def format_age_minutes(age: Any) -> str:
    """Human age label — never emits Nonem/nullm."""
    if age is None:
        return FRESHNESS_UNAVAILABLE
    try:
        n = int(age)
    except (TypeError, ValueError):
        return FRESHNESS_UNAVAILABLE
    if n < 0:
        return FRESHNESS_UNAVAILABLE
    if n < 60:
        return f'{n}m'
    if n < 24 * 60:
        return f'{n // 60}h {n % 60}m'
    return f'{n // (24 * 60)}d'


def format_freshness_display(
    *,
    age_minutes: Any = None,
    timestamp: Any = None,
    stale: bool = False,
) -> Dict[str, Any]:
    """Canonical freshness display block for API/GUI/Telegram."""
    age = age_minutes if age_minutes is not None else (
        age_minutes_fn(timestamp) if timestamp is not None else None
    )
    if age is None and timestamp is not None:
        age = age_minutes(timestamp)
    available = age is not None
    tier = freshness_health_tier(age)
    stale_flag = bool(stale) or tier == 'stale'
    return {
        'age_minutes': age,
        'age_display': format_age_minutes(age),
        'freshness_available': available,
        'freshness_unavailable': not available,
        'health_tier': tier,
        'stale': stale_flag,
        'status_label': (
            'stale' if stale_flag else (
                'aging' if tier == 'aging' else (
                    'fresh' if tier == 'healthy' else FRESHNESS_UNAVAILABLE
                )
            )
        ),
    }


def age_minutes_fn(value: Any) -> Optional[int]:
    return age_minutes(value)


def validate_timestamp_order(
    earlier: Any,
    later: Any,
) -> Tuple[bool, Optional[str]]:
    """Return (ok, issue) — flags future or inverted timestamps."""
    a = normalize_timestamp(earlier)
    b = normalize_timestamp(later)
    if a is None or b is None:
        return True, None
    now = datetime.now(IST)
    if a > now:
        return False, 'future_timestamp'
    if b > now:
        return False, 'future_timestamp'
    if a > b:
        return False, 'timestamp_order_inverted'
    return True, None


def merge_freshness_payload(base: Optional[dict], *, timestamp: Any = None) -> dict:
    """Enrich freshness dict with normalized age fields."""
    out = dict(base or {})
    age = out.get('age_minutes')
    if age is None and timestamp is not None:
        age = age_minutes(timestamp)
    if age is None:
        pub = out.get('published_at') or out.get('snapshot_published_at')
        age = age_minutes(pub)
    display = format_freshness_display(age_minutes=age, stale=bool(out.get('stale')))
    out.update(display)
    if out.get('age_minutes') is None:
        out['age_minutes'] = None
        out['age_display'] = FRESHNESS_UNAVAILABLE
    return out
