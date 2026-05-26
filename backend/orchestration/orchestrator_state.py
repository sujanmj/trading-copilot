"""
Persistent orchestrator heartbeat — cross-component runtime ownership.

Writes data/orchestrator_state.json for autonomous recovery, health checks,
and GUI/API synchronization validation.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR, IS_RAILWAY

IST = pytz.timezone('Asia/Kolkata')
ORCHESTRATOR_STATE_FILE = DATA_DIR / 'orchestrator_state.json'

MODE_PRIMARY = 'PRIMARY'
MODE_API_ONLY = 'API_ONLY'
MODE_RECOVERING = 'RECOVERING'
MODE_STALE = 'STALE'

TICK_STALE_SECONDS = 120
LOCK_HEARTBEAT_STALE_SECONDS = 600
OWNER_UNHEALTHY_SECONDS = 120


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _host_id() -> str:
    return (
        os.environ.get('RAILWAY_REPLICA_ID')
        or os.environ.get('RAILWAY_SERVICE_ID')
        or os.environ.get('HOSTNAME')
        or 'local'
    )


def default_state() -> dict:
    return {
        'heartbeat_at': None,
        'orchestrator_mode': MODE_RECOVERING,
        'owner_pid': None,
        'owner_start_time': None,
        'api_pid': None,
        'last_scheduler_tick': None,
        'last_scheduler_tick_unix': None,
        'last_eod_completion': None,
        'lock_age_seconds': None,
        'lock_valid': False,
        'recovery_attempts': 0,
        'recovery_attempts_today': 0,
        'recovery_day': None,
        'last_recovery_at': None,
        'last_recovery_reason': None,
        'last_recovery_result': None,
        'runtime_healthy': False,
        'host': _host_id(),
        'railway': IS_RAILWAY,
        'started_at': _now_iso(),
        'components': {
            'scheduler': {'status': 'unknown', 'lock_valid': False},
            'lifecycle': {'pipeline_status': 'IDLE'},
            'exports': {'fresh': False},
            'gui_sync': {'validated': False},
        },
        'recovery_history': [],
    }


def load_orchestrator_state() -> dict:
    if not ORCHESTRATOR_STATE_FILE.exists():
        return default_state()
    try:
        import json
        with open(ORCHESTRATOR_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default_state()
        base = default_state()
        base.update(data)
        return base
    except Exception:
        return default_state()


def save_orchestrator_state(state: dict) -> dict:
    state = dict(state)
    state['heartbeat_at'] = _now_iso()
    atomic_write_json(ORCHESTRATOR_STATE_FILE, state)
    return state


def _log_orchestrator(message: str):
    print(f"[ORCHESTRATOR] {message}", flush=True)


def set_mode(mode: str, *, reason: Optional[str] = None, extra: Optional[dict] = None) -> dict:
    state = load_orchestrator_state()
    prev = state.get('orchestrator_mode')
    if prev != mode:
        _log_orchestrator(f"mode {prev or 'none'} -> {mode}" + (f" ({reason})" if reason else ''))
    state['orchestrator_mode'] = mode
    if extra:
        state.update(extra)
    return save_orchestrator_state(state)


def record_recovery_attempt(reason: str, result: str, *, detail: Optional[str] = None) -> dict:
    state = load_orchestrator_state()
    today = datetime.now(IST).strftime('%Y-%m-%d')
    if state.get('recovery_day') != today:
        state['recovery_day'] = today
        state['recovery_attempts_today'] = 0
    state['recovery_attempts'] = int(state.get('recovery_attempts') or 0) + 1
    state['recovery_attempts_today'] = int(state.get('recovery_attempts_today') or 0) + 1
    state['last_recovery_at'] = _now_iso()
    state['last_recovery_reason'] = reason
    state['last_recovery_result'] = result
    history: List[dict] = list(state.get('recovery_history') or [])
    history.append({
        'at': _now_iso(),
        'reason': reason,
        'result': result,
        'detail': detail,
        'attempt': state['recovery_attempts_today'],
    })
    state['recovery_history'] = history[-30:]
    _log_orchestrator(f"recovery attempt #{state['recovery_attempts_today']} — {reason} -> {result}")
    return save_orchestrator_state(state)


def mark_primary_acquired(scheduler_pid: int) -> dict:
    state = load_orchestrator_state()
    state['owner_pid'] = scheduler_pid
    state['owner_start_time'] = _now_iso()
    state['orchestrator_mode'] = MODE_PRIMARY
    state['runtime_healthy'] = True
    state['components'] = state.get('components') or {}
    state['components']['scheduler'] = {
        'status': 'healthy',
        'lock_valid': True,
        'pid': scheduler_pid,
    }
    save_orchestrator_state(state)
    _log_orchestrator(f"PRIMARY acquired pid={scheduler_pid}")
    return state


def mark_api_only(reason: str = 'duplicate_runtime') -> dict:
    return set_mode(MODE_API_ONLY, reason=reason, extra={'runtime_healthy': False})


def record_scheduler_tick(scheduler_pid: Optional[int] = None) -> dict:
    state = load_orchestrator_state()
    now = time.time()
    state['last_scheduler_tick'] = _now_iso()
    state['last_scheduler_tick_unix'] = now
    if scheduler_pid:
        state['owner_pid'] = scheduler_pid
    state['orchestrator_mode'] = MODE_PRIMARY
    state['runtime_healthy'] = True
    components = dict(state.get('components') or {})
    sched = dict(components.get('scheduler') or {})
    sched.update({'status': 'healthy', 'lock_valid': True, 'last_tick_at': state['last_scheduler_tick']})
    components['scheduler'] = sched
    state['components'] = components
    return save_orchestrator_state(state)


def record_eod_completion(iso_ts: Optional[str] = None) -> dict:
    state = load_orchestrator_state()
    state['last_eod_completion'] = iso_ts or _now_iso()
    return save_orchestrator_state(state)


def bootstrap_api_runtime(api_pid: int) -> dict:
    state = load_orchestrator_state()
    state['api_pid'] = api_pid
    if not state.get('started_at'):
        state['started_at'] = _now_iso()
    state['host'] = _host_id()
    state['railway'] = IS_RAILWAY
    return save_orchestrator_state(state)


def _tick_age_seconds(state: dict) -> Optional[float]:
    ts = state.get('last_scheduler_tick_unix')
    if ts is None:
        return None
    try:
        return max(0.0, time.time() - float(ts))
    except (TypeError, ValueError):
        return None


def _lock_age_seconds() -> Optional[float]:
    from backend.utils.process_lock import lock_status
    sched = lock_status().get('master_scheduler') or {}
    started = sched.get('started_at')
    if started is None:
        return None
    try:
        return max(0.0, time.time() - float(started))
    except (TypeError, ValueError):
        return None


def validate_singleton_ownership() -> Dict[str, Any]:
    """Return ownership diagnosis for autonomous recovery."""
    from backend.utils.process_lock import is_lock_holder_valid, lock_status

    state = load_orchestrator_state()
    locks = lock_status()
    sched_lock = locks.get('master_scheduler') or {}
    lock_valid = bool(sched_lock.get('valid'))
    tick_age = _tick_age_seconds(state)
    lock_age = _lock_age_seconds()

    issues: List[str] = []
    if lock_valid and tick_age is not None and tick_age > TICK_STALE_SECONDS:
        issues.append(f'scheduler_tick_stale:{int(tick_age)}s')
    if lock_valid and tick_age is None:
        issues.append('lock_valid_but_no_tick')
    if not lock_valid and sched_lock.get('pid'):
        issues.append('stale_lock_file')
    if lock_age is not None and lock_age > LOCK_HEARTBEAT_STALE_SECONDS:
        if tick_age is None or tick_age > LOCK_HEARTBEAT_STALE_SECONDS:
            issues.append(f'lock_age_stale:{int(lock_age)}s')

    healthy = lock_valid and tick_age is not None and tick_age <= TICK_STALE_SECONDS
    if lock_valid and tick_age is None and (lock_age or 0) < OWNER_UNHEALTHY_SECONDS:
        healthy = True  # grace after fresh acquire

    return {
        'healthy': healthy,
        'lock_valid': lock_valid,
        'lock_age_seconds': int(lock_age) if lock_age is not None else None,
        'tick_age_seconds': int(tick_age) if tick_age is not None else None,
        'owner_pid': sched_lock.get('pid') or state.get('owner_pid'),
        'issues': issues,
        'mode': state.get('orchestrator_mode'),
    }


def refresh_component_snapshot() -> dict:
    """Aggregate lifecycle + export freshness into orchestrator state."""
    state = load_orchestrator_state()
    ownership = validate_singleton_ownership()

    try:
        from backend.lifecycle.prediction_lifecycle_engine import get_lifecycle_status
        lifecycle = get_lifecycle_status()
    except Exception:
        lifecycle = {'pipeline_status': 'UNKNOWN', 'exports_fresh': False}

    exports_fresh = bool(lifecycle.get('exports_fresh'))
    gui_ok = (
        lifecycle.get('pipeline_status') == 'COMPLETE'
        and exports_fresh
        and ownership.get('healthy')
    )

    state['lock_valid'] = ownership.get('lock_valid')
    state['lock_age_seconds'] = ownership.get('lock_age_seconds')
    state['runtime_healthy'] = ownership.get('healthy')
    state['components'] = {
        'scheduler': {
            'status': 'healthy' if ownership.get('healthy') else 'stale',
            'lock_valid': ownership.get('lock_valid'),
            'tick_age_seconds': ownership.get('tick_age_seconds'),
            'issues': ownership.get('issues'),
        },
        'lifecycle': {
            'pipeline_status': lifecycle.get('pipeline_status'),
            'exports_fresh': exports_fresh,
            'last_eod_cycle_at': lifecycle.get('last_eod_cycle_at'),
        },
        'exports': {
            'fresh': exports_fresh,
            'stats_age_minutes': lifecycle.get('stats_age_minutes'),
            'history_age_minutes': lifecycle.get('history_age_minutes'),
        },
        'gui_sync': {
            'validated': gui_ok,
            'brain_fresh': lifecycle.get('brain_age_minutes') is not None and lifecycle.get('brain_age_minutes', 9999) < 360,
        },
    }
    if not ownership.get('healthy'):
        state['orchestrator_mode'] = MODE_STALE
    elif state.get('orchestrator_mode') not in (MODE_PRIMARY, MODE_RECOVERING):
        state['orchestrator_mode'] = MODE_PRIMARY

    return save_orchestrator_state(state)


def get_orchestrator_health_payload() -> dict:
    state = refresh_component_snapshot()
    ownership = validate_singleton_ownership()
    return {
        'orchestrator_mode': state.get('orchestrator_mode'),
        'runtime_healthy': state.get('runtime_healthy'),
        'owner_pid': state.get('owner_pid'),
        'last_scheduler_tick': state.get('last_scheduler_tick'),
        'tick_age_seconds': ownership.get('tick_age_seconds'),
        'lock_valid': ownership.get('lock_valid'),
        'lock_age_seconds': ownership.get('lock_age_seconds'),
        'recovery_attempts_today': state.get('recovery_attempts_today'),
        'last_recovery_at': state.get('last_recovery_at'),
        'last_recovery_reason': state.get('last_recovery_reason'),
        'components': state.get('components'),
        'issues': ownership.get('issues'),
    }
