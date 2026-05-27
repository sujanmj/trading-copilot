"""
Runtime audit trail — stale transitions, lifecycle conflicts, metric/freshness violations.
"""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
AUDIT_FILE = DATA_DIR / 'runtime_audit.json'
MAX_EVENTS = 200

_EVENT_TYPES = frozenset({
    'stale_transition',
    'lifecycle_conflict',
    'metric_conflict',
    'freshness_violation',
    'regime_mismatch',
    'scheduler_drift',
    'duplicate_alert',
})


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _load_audit() -> dict:
    if not AUDIT_FILE.exists():
        return {'events': [], 'counters': {}, 'updated_at': None}
    try:
        data = json.loads(AUDIT_FILE.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return {'events': [], 'counters': {}, 'updated_at': None}
        data.setdefault('events', [])
        data.setdefault('counters', {})
        return data
    except Exception:
        return {'events': [], 'counters': {}, 'updated_at': None}


def record_audit_event(
    event_type: str,
    detail: str,
    *,
    severity: str = 'warn',
    context: Optional[dict] = None,
) -> None:
    if event_type not in _EVENT_TYPES:
        event_type = 'metric_conflict'
    state = _load_audit()
    events: List[dict] = list(state.get('events') or [])
    events.append({
        'at': _now_iso(),
        'type': event_type,
        'severity': severity,
        'detail': str(detail)[:500],
        'context': context or {},
    })
    state['events'] = events[-MAX_EVENTS:]
    counters = dict(state.get('counters') or {})
    counters[event_type] = int(counters.get(event_type) or 0) + 1
    state['counters'] = counters
    state['updated_at'] = _now_iso()
    atomic_write_json(AUDIT_FILE, state)


def record_metric_conflicts(issues: List[str]) -> None:
    for issue in issues:
        kind = 'metric_conflict'
        if issue.startswith('lifecycle'):
            kind = 'lifecycle_conflict'
        elif 'fresh' in issue or 'stale' in issue:
            kind = 'freshness_violation'
        elif 'regime' in issue:
            kind = 'regime_mismatch'
        record_audit_event(kind, issue)


def record_stale_transition(was_fresh: bool, now_stale: bool, detail: str = '') -> None:
    if was_fresh and now_stale:
        record_audit_event('stale_transition', detail or 'snapshot became stale')


def record_duplicate_alert(ticker: str, reason: str) -> None:
    record_audit_event('duplicate_alert', f'{ticker}:{reason}', context={'ticker': ticker})


def record_scheduler_drift(detail: str) -> None:
    record_audit_event('scheduler_drift', detail, severity='error')


def get_audit_report(*, limit: int = 50) -> Dict[str, Any]:
    state = _load_audit()
    events = list(state.get('events') or [])[-limit:]
    counters = dict(state.get('counters') or {})
    recent_by_type: Dict[str, int] = {}
    for ev in events:
        t = ev.get('type', 'unknown')
        recent_by_type[t] = recent_by_type.get(t, 0) + 1
    return {
        'status': 'ok',
        'updated_at': state.get('updated_at'),
        'total_events': sum(int(v) for v in counters.values()),
        'counters': counters,
        'recent_by_type': recent_by_type,
        'events': list(reversed(events)),
    }


def audit_from_runtime_state(state: dict) -> None:
    """Record audit events from validation issues on runtime state build."""
    ok, issues = False, []
    try:
        from backend.validation.metric_consistency_guard import validate_metric_consistency
        ok, issues = validate_metric_consistency(state)
    except Exception as exc:
        record_audit_event('metric_conflict', f'guard_failed:{exc}')
        return
    if not ok:
        record_metric_conflicts(issues)
    fresh = state.get('snapshot_freshness') or {}
    if fresh.get('stale'):
        record_audit_event('freshness_violation', 'active snapshot stale', context=fresh)
    lc = state.get('lifecycle') or {}
    if not lc.get('transition_valid'):
        record_audit_event('lifecycle_conflict', lc.get('transition_reason', 'invalid transition'))
