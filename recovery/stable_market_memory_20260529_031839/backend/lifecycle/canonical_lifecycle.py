"""
Canonical lifecycle states — single authority for market/session phase.

States: PRE_MARKET, MARKET_ACTIVE, POST_MARKET, AFTER_HOURS, WEEKEND, HOLIDAY, DEGRADED
No overlapping MARKET_ACTIVE + COMPLETE + POST_MARKET.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Dict, Optional, Tuple

import pytz

IST = pytz.timezone('Asia/Kolkata')

PRE_MARKET = 'PRE_MARKET'
MARKET_ACTIVE = 'MARKET_ACTIVE'
POST_MARKET = 'POST_MARKET'
AFTER_HOURS = 'AFTER_HOURS'
WEEKEND = 'WEEKEND'
HOLIDAY = 'HOLIDAY'
DEGRADED = 'DEGRADED'

CANONICAL_STATES = frozenset({
    PRE_MARKET, MARKET_ACTIVE, POST_MARKET, AFTER_HOURS, WEEKEND, HOLIDAY, DEGRADED,
})

# Legacy market_hours labels → canonical
_LEGACY_MAP = {
    'PREMARKET_PREP': PRE_MARKET,
    'PRE_MARKET': PRE_MARKET,
    'MARKET_ACTIVE': MARKET_ACTIVE,
    'POSTMARKET_EVAL': POST_MARKET,
    'POST_MARKET': POST_MARKET,
    'OVERNIGHT_INTEL': AFTER_HOURS,
    'NIGHT_IDLE': AFTER_HOURS,
    'CLOSED': AFTER_HOURS,
    'AFTER_HOURS': AFTER_HOURS,
    'WEEKEND': WEEKEND,
    'HOLIDAY': HOLIDAY,
}

# Mutually exclusive terminal pipeline labels that must not overlap MARKET_ACTIVE
_PIPELINE_CONFLICTS = frozenset({'COMPLETE', 'POSTMARKET_EVAL', 'POST_MARKET'})

# IST session boundaries (NSE)
_MARKET_OPEN = time(9, 15)
_MARKET_ACTIVE_END = time(15, 29)
_POST_MARKET_START = time(15, 31)
_AFTER_HOURS_START = time(17, 0)
_PRE_MARKET_START = time(8, 30)
_NIGHT_START = time(23, 0)


def _now(now: Optional[datetime] = None) -> datetime:
    n = now or datetime.now(IST)
    return n.astimezone(IST) if n.tzinfo else IST.localize(n)


def _is_holiday(now: datetime) -> bool:
    try:
        from backend.utils.market_hours import is_market_holiday
        return bool(is_market_holiday(now))
    except Exception:
        return False


def _market_period(now: Optional[datetime] = None) -> str:
    from backend.utils.market_hours import get_market_period
    return get_market_period(now)


def resolve_base_lifecycle(now: Optional[datetime] = None) -> str:
    """Map IST clock to canonical lifecycle (before degradation overlay)."""
    now = _now(now)
    if _is_holiday(now):
        return HOLIDAY
    if now.weekday() >= 5:
        return WEEKEND
    period = _market_period(now)
    mapping = {
        'pre_market': PRE_MARKET,
        'market': MARKET_ACTIVE,
        'post_market': POST_MARKET,
        'after_hours': AFTER_HOURS,
        'night': AFTER_HOURS,
    }
    return mapping.get(period, AFTER_HOURS)


def from_legacy_label(label: Optional[str]) -> str:
    key = str(label or '').upper().strip()
    return _LEGACY_MAP.get(key, key if key in CANONICAL_STATES else AFTER_HOURS)


def is_after_hours_mode(state: Optional[str] = None, *, now: Optional[datetime] = None) -> bool:
    """True when trading/execution language should be suppressed."""
    st = from_legacy_label(state) if state else resolve_base_lifecycle(now)
    return st in (AFTER_HOURS, POST_MARKET, WEEKEND, HOLIDAY)


def is_market_active(state: Optional[str] = None, *, now: Optional[datetime] = None) -> bool:
    st = from_legacy_label(state) if state else resolve_base_lifecycle(now)
    return st == MARKET_ACTIVE


def apply_degradation(
    base_state: str,
    *,
    snapshot_stale: bool = False,
    orchestrator_unhealthy: bool = False,
    metric_conflicts: bool = False,
) -> str:
    if snapshot_stale or orchestrator_unhealthy or metric_conflicts:
        return DEGRADED
    return base_state


def validate_transition(
    current: str,
    proposed: str,
    *,
    pipeline_status: Optional[str] = None,
) -> Tuple[bool, str]:
    """Guard against impossible lifecycle overlaps."""
    cur = from_legacy_label(current)
    nxt = from_legacy_label(proposed)
    if nxt not in CANONICAL_STATES:
        return False, f'invalid_state:{nxt}'
    pipe = str(pipeline_status or '').upper()
    if cur == MARKET_ACTIVE and pipe in _PIPELINE_CONFLICTS:
        return False, f'market_active_pipeline_conflict:{pipe}'
    if cur == POST_MARKET and nxt == MARKET_ACTIVE:
        return False, 'cannot_reopen_from_post_market_same_day'
    if cur in (AFTER_HOURS, WEEKEND, HOLIDAY) and nxt == MARKET_ACTIVE:
        return False, 'cannot_be_market_active_after_close'
    return True, 'ok'


def lifecycle_display(state: str) -> str:
    display = {
        PRE_MARKET: 'Pre-Market Analysis',
        MARKET_ACTIVE: 'Market Active',
        POST_MARKET: 'Post-Market Evaluation',
        AFTER_HOURS: 'After-Hours Intelligence Mode',
        WEEKEND: 'Weekend — Market Closed',
        HOLIDAY: 'Holiday — Market Closed',
        DEGRADED: 'Degraded — Stale or Conflicting State',
    }
    return display.get(from_legacy_label(state), state)


def build_canonical_lifecycle(
    *,
    now: Optional[datetime] = None,
    snapshot_stale: bool = False,
    orchestrator_unhealthy: bool = False,
    metric_conflicts: bool = False,
    pipeline_status: Optional[str] = None,
) -> Dict[str, Any]:
    base = resolve_base_lifecycle(now)
    state = apply_degradation(
        base,
        snapshot_stale=snapshot_stale,
        orchestrator_unhealthy=orchestrator_unhealthy,
        metric_conflicts=metric_conflicts,
    )
    ok, reason = validate_transition(state, state, pipeline_status=pipeline_status)
    after_hours = is_after_hours_mode(state)
    return {
        'lifecycle_state': state,
        'lifecycle_base': base,
        'lifecycle_display': lifecycle_display(state),
        'transition_valid': ok,
        'transition_reason': reason,
        'market_period': _market_period(now),
        'pipeline_status': pipeline_status,
        'after_hours_mode': after_hours,
        'suppress_trading_language': after_hours or state == DEGRADED,
        'session_message': (
            'After-hours intelligence mode active'
            if after_hours and state != DEGRADED
            else None
        ),
        'collectors_may_run': True,
        'market_session_open': base == MARKET_ACTIVE,
    }


def sync_with_scheduler() -> Dict[str, Any]:
    """Align lifecycle with market_hours + orchestrator heartbeat."""
    now = _now()
    snapshot_stale = False
    orchestrator_unhealthy = False
    metric_conflicts = False
    pipeline_status = None
    try:
        from backend.intelligence.active_snapshot import snapshot_health
        snapshot_stale = bool((snapshot_health() or {}).get('stale'))
    except Exception:
        pass
    try:
        from backend.orchestration.orchestrator_state import validate_singleton_ownership
        ownership = validate_singleton_ownership()
        orchestrator_unhealthy = not ownership.get('healthy')
    except Exception:
        pass
    try:
        from backend.lifecycle.prediction_lifecycle_engine import get_lifecycle_status
        pipeline_status = (get_lifecycle_status() or {}).get('pipeline_status')
    except Exception:
        pass
    return build_canonical_lifecycle(
        now=now,
        snapshot_stale=snapshot_stale,
        orchestrator_unhealthy=orchestrator_unhealthy,
        metric_conflicts=metric_conflicts,
        pipeline_status=pipeline_status,
    )
