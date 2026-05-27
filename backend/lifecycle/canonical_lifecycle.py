"""
Canonical lifecycle states — single authority for market/session phase.

States: PRE_MARKET, MARKET_ACTIVE, POST_MARKET, CLOSED, DEGRADED
No overlapping MARKET_ACTIVE + COMPLETE + POST_MARKET.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pytz

IST = pytz.timezone('Asia/Kolkata')

PRE_MARKET = 'PRE_MARKET'
MARKET_ACTIVE = 'MARKET_ACTIVE'
POST_MARKET = 'POST_MARKET'
CLOSED = 'CLOSED'
DEGRADED = 'DEGRADED'

CANONICAL_STATES = frozenset({PRE_MARKET, MARKET_ACTIVE, POST_MARKET, CLOSED, DEGRADED})

# Legacy market_hours labels → canonical
_LEGACY_MAP = {
    'PREMARKET_PREP': PRE_MARKET,
    'MARKET_ACTIVE': MARKET_ACTIVE,
    'POSTMARKET_EVAL': POST_MARKET,
    'OVERNIGHT_INTEL': POST_MARKET,
    'NIGHT_IDLE': CLOSED,
}

# Mutually exclusive terminal pipeline labels that must not overlap MARKET_ACTIVE
_PIPELINE_CONFLICTS = frozenset({'COMPLETE', 'POSTMARKET_EVAL', 'POST_MARKET'})


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(IST)


def _market_period(now: Optional[datetime] = None) -> str:
    from backend.utils.market_hours import get_market_period
    return get_market_period(now)


def resolve_base_lifecycle(now: Optional[datetime] = None) -> str:
    """Map IST clock to canonical lifecycle (before degradation overlay)."""
    period = _market_period(now)
    mapping = {
        'pre_market': PRE_MARKET,
        'market': MARKET_ACTIVE,
        'after_hours': POST_MARKET,
        'night': CLOSED,
        'weekend': CLOSED,
    }
    return mapping.get(period, CLOSED)


def from_legacy_label(label: Optional[str]) -> str:
    key = str(label or '').upper().strip()
    return _LEGACY_MAP.get(key, key if key in CANONICAL_STATES else CLOSED)


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
    return True, 'ok'


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
    display = {
        PRE_MARKET: 'Pre-Market Analysis',
        MARKET_ACTIVE: 'Market Active',
        POST_MARKET: 'Post-Market Evaluation',
        CLOSED: 'Market Closed',
        DEGRADED: 'Degraded — Stale or Conflicting State',
    }
    return {
        'lifecycle_state': state,
        'lifecycle_base': base,
        'lifecycle_display': display.get(state, state),
        'transition_valid': ok,
        'transition_reason': reason,
        'market_period': _market_period(now),
        'pipeline_status': pipeline_status,
    }


def sync_with_scheduler() -> Dict[str, Any]:
    """Align lifecycle with market_hours + orchestrator heartbeat."""
    now = _now()
    snapshot_stale = False
    orchestrator_unhealthy = False
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
        pipeline_status=pipeline_status,
    )
