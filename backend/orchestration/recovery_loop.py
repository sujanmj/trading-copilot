"""
Autonomous self-healing orchestration recovery loop.

detect → diagnose → recover → verify (no manual intervention)
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz

from backend.orchestration.orchestrator_state import (
    MODE_API_ONLY,
    MODE_PRIMARY,
    MODE_RECOVERING,
    OWNER_UNHEALTHY_SECONDS,
    bootstrap_api_runtime,
    load_orchestrator_state,
    mark_api_only,
    mark_primary_acquired,
    record_recovery_attempt,
    refresh_component_snapshot,
    save_orchestrator_state,
    set_mode,
    validate_singleton_ownership,
)
from backend.utils.config import DATA_DIR, IS_RAILWAY

IST = pytz.timezone('Asia/Kolkata')

HEALTH_TICK_SECONDS = 60
RECOVERY_COOLDOWN_SECONDS = 45
MAX_RECOVERY_PER_HOUR = 12

_recovery_lock = threading.Lock()
_last_health_tick = 0.0
_last_recovery_at = 0.0
_recovery_hour_bucket = ''
_recovery_hour_count = 0
_scheduler_unhealthy_since: Optional[float] = None
_force_scheduler_retry = threading.Event()


def _log(tag: str, message: str):
    print(f"[{tag}] {message}", flush=True)


def request_scheduler_retry():
    """Signal scheduler subprocess loop to retry immediately."""
    _force_scheduler_retry.set()


def should_force_scheduler_retry() -> bool:
    if _force_scheduler_retry.is_set():
        _force_scheduler_retry.clear()
        return True
    return False


def detect_duplicate_workers() -> List[str]:
    issues = []
    workers = os.environ.get('WEB_CONCURRENCY') or os.environ.get('UVICORN_WORKERS')
    if workers and str(workers).strip() not in ('', '1', '0'):
        issues.append(f'multi_worker_env:{workers}')
    if os.environ.get('DISABLE_SCHEDULER') == '1':
        issues.append('scheduler_disabled')
    return issues


def enforce_single_worker_mode():
    """Railway-safe: force single uvicorn worker semantics."""
    os.environ.setdefault('WEB_CONCURRENCY', '1')
    os.environ.pop('UVICORN_WORKERS', None)
    dupes = detect_duplicate_workers()
    if dupes:
        _log('ORCHESTRATOR', f'duplicate runtime signals: {", ".join(dupes)}')
        if 'scheduler_disabled' not in dupes:
            _log('ORCHESTRATOR', 'forcing WEB_CONCURRENCY=1 for singleton orchestrator')


def safe_clear_stale_locks(reason: str = 'autonomous_recovery') -> bool:
    from backend.utils.process_lock import clear_stale_lock, is_lock_holder_valid, force_clear_lock

    ownership = validate_singleton_ownership()
    tick_age = ownership.get('tick_age_seconds')

    if tick_age is not None and tick_age > OWNER_UNHEALTHY_SECONDS:
        if force_clear_lock('master_scheduler', f'{reason}:tick_stale_{int(tick_age)}s'):
            record_recovery_attempt(reason, 'lock_force_cleared', detail=f'tick_age={tick_age}')
            return True

    if is_lock_holder_valid('master_scheduler'):
        return False
    cleared = clear_stale_lock('master_scheduler')
    if cleared:
        _log('ORCHESTRATOR', f'stale lock detected — cleared ({reason})')
        record_recovery_attempt(reason, 'lock_cleared', detail='master_scheduler')
    return cleared


def diagnose_runtime() -> Dict[str, Any]:
    ownership = validate_singleton_ownership()
    state = load_orchestrator_state()
    issues = list(ownership.get('issues') or [])
    issues.extend(detect_duplicate_workers())

    tick_age = ownership.get('tick_age_seconds')
    if ownership.get('lock_valid') and tick_age is not None and tick_age > OWNER_UNHEALTHY_SECONDS:
        issues.append(f'orchestrator_unhealthy:{tick_age}s')
    if not ownership.get('lock_valid') and not ownership.get('healthy'):
        issues.append('no_valid_orchestrator')

    try:
        from backend.lifecycle.prediction_lifecycle_engine import get_lifecycle_status
        lc = get_lifecycle_status()
        if lc.get('pipeline_status') == 'STALE':
            issues.append('lifecycle_stale')
        if lc.get('pipeline_status') == 'COMPLETE' and not lc.get('exports_fresh'):
            issues.append('exports_stale_after_eod')
    except Exception as e:
        issues.append(f'lifecycle_check_error:{e}')

    return {
        'healthy': ownership.get('healthy') and 'no_valid_orchestrator' not in issues,
        'ownership': ownership,
        'issues': issues,
        'mode': state.get('orchestrator_mode'),
        'tick_age_seconds': tick_age,
    }


def verify_lifecycle_exports() -> Dict[str, Any]:
    """Check post-EOD artifacts; return missing components."""
    missing = []
    checks = {
        'stats': DATA_DIR / 'stats_data.json',
        'history': DATA_DIR / 'history_data.json',
        'active_predictions': DATA_DIR / 'active_predictions.json',
        'intelligence': DATA_DIR / 'unified_intelligence.json',
    }
    cal_dir = DATA_DIR / 'calibration_history.json'
    checks['calibration'] = cal_dir

    now = time.time()
    for name, path in checks.items():
        if not path.exists():
            missing.append(f'{name}_missing')
            continue
        age_h = (now - path.stat().st_mtime) / 3600
        if age_h > 12:
            missing.append(f'{name}_stale')

    try:
        from backend.lifecycle.lifecycle_tracing import load_lifecycle_state
        state = load_lifecycle_state()
        if state.get('pipeline_status') == 'COMPLETE':
            for stage in ('stats_export', 'history_export', 'brain_refresh'):
                if not state.get({
                    'stats_export': 'last_stats_export',
                    'history_export': 'last_history_export',
                    'brain_refresh': 'last_brain_refresh',
                }.get(stage)):
                    missing.append(f'stage_not_marked:{stage}')
    except Exception:
        pass

    ok = len(missing) == 0
    if ok:
        _log('LIFECYCLE VERIFY', 'exports validated')
    else:
        _log('LIFECYCLE VERIFY', f'gaps: {", ".join(missing)}')
    return {'ok': ok, 'missing': missing}


def trigger_partial_lifecycle_replay(missing: List[str]) -> bool:
    """Replay EOD when exports incomplete after expected completion."""
    if not missing:
        return False
    _log('ORCHESTRATOR', f'partial lifecycle replay — {", ".join(missing[:5])}')
    set_mode(MODE_RECOVERING, reason='partial_lifecycle_replay')
    try:
        from backend.orchestration.master_scheduler import run_post_market_pipeline
        run_post_market_pipeline(force=True, trigger='autonomous:partial_replay')
        record_recovery_attempt('partial_lifecycle_replay', 'triggered', detail=','.join(missing[:8]))
        return True
    except Exception as e:
        record_recovery_attempt('partial_lifecycle_replay', 'failed', detail=str(e))
        _log('ORCHESTRATOR', f'partial replay failed: {e}')
        return False


def verify_gui_sync() -> Dict[str, Any]:
    snap = refresh_component_snapshot()
    components = snap.get('components') or {}
    gui = components.get('gui_sync') or {}
    lifecycle = components.get('lifecycle') or {}
    exports = components.get('exports') or {}
    scheduler = components.get('scheduler') or {}

    validated = (
        scheduler.get('status') == 'healthy'
        and lifecycle.get('pipeline_status') in ('COMPLETE', 'RUNNING', 'RECOVERING')
        and (exports.get('fresh') or lifecycle.get('pipeline_status') != 'COMPLETE')
    )
    if validated:
        _log('GUI SYNC', 'exports validated')
    else:
        _log('GUI SYNC', f'stale — scheduler={scheduler.get("status")} lifecycle={lifecycle.get("pipeline_status")}')
    return {'validated': validated, 'components': components}


def attempt_orchestrator_recovery(reason: str) -> bool:
    """Clear stale locks and signal scheduler relaunch."""
    global _last_recovery_at

    now = time.time()
    with _recovery_lock:
        if now - _last_recovery_at < RECOVERY_COOLDOWN_SECONDS:
            return False

        hour_key = datetime.now(IST).strftime('%Y-%m-%d-%H')
        global _recovery_hour_bucket, _recovery_hour_count
        if _recovery_hour_bucket != hour_key:
            _recovery_hour_bucket = hour_key
            _recovery_hour_count = 0
        if _recovery_hour_count >= MAX_RECOVERY_PER_HOUR:
            _log('ORCHESTRATOR', 'recovery rate limited — max attempts this hour')
            return False

        set_mode(MODE_RECOVERING, reason=reason)
        cleared = safe_clear_stale_locks(reason)
        request_scheduler_retry()
        _last_recovery_at = now
        _recovery_hour_count += 1
        record_recovery_attempt(reason, 'recovery_triggered', detail=f'lock_cleared={cleared}')
        return True


def handle_scheduler_singleton_exit(exit_code: int) -> str:
    """
    Decide next action when scheduler subprocess exits.
    Returns: retry_immediate | wait_primary | api_only
    """
    ownership = validate_singleton_ownership()
    tick_age = ownership.get('tick_age_seconds')

    if tick_age is not None and tick_age > OWNER_UNHEALTHY_SECONDS:
        safe_clear_stale_locks('singleton_exit_stale_tick')
        return 'retry_immediate'

    if not ownership.get('lock_valid'):
        safe_clear_stale_locks('singleton_exit_stale_lock')
        return 'retry_immediate'

    if exit_code == 75:
        if tick_age is None:
            safe_clear_stale_locks('singleton_exit_no_heartbeat')
            return 'retry_immediate'
        return 'wait_primary'

    return 'wait_primary'


def bootstrap_self_healing(api_pid: Optional[int] = None) -> dict:
    enforce_single_worker_mode()
    pid = api_pid or os.getpid()
    bootstrap_api_runtime(pid)

    dupes = detect_duplicate_workers()
    if 'scheduler_disabled' in dupes:
        mark_api_only('scheduler_disabled')
        _log('ORCHESTRATOR', 'API_ONLY — scheduler disabled by env')
        return load_orchestrator_state()

    cleared = safe_clear_stale_locks('startup_bootstrap')
    if cleared:
        request_scheduler_retry()
    set_mode(MODE_RECOVERING, reason='startup_bootstrap')
    _log('ORCHESTRATOR', 'self-healing bootstrap complete')
    return refresh_component_snapshot()


def run_orchestrator_health_tick() -> Dict[str, Any]:
    """60s health verification — called from API recovery thread."""
    global _last_health_tick, _scheduler_unhealthy_since

    now = time.time()
    if now - _last_health_tick < HEALTH_TICK_SECONDS - 5:
        return {'skipped': True}
    _last_health_tick = now

    diag = diagnose_runtime()
    snap = refresh_component_snapshot()

    if diag.get('healthy'):
        _scheduler_unhealthy_since = None
        if snap.get('orchestrator_mode') != MODE_API_ONLY:
            set_mode(MODE_PRIMARY, reason='health_tick_ok')
        _log('ORCHESTRATOR', 'runtime healthy')

        missing = verify_lifecycle_exports()
        if not missing.get('ok'):
            today = datetime.now(IST)
            if today.weekday() < 5 and (today.hour > 16 or (today.hour == 16 and today.minute >= 0)):
                trigger_partial_lifecycle_replay(missing.get('missing') or [])

        verify_gui_sync()
        return {'healthy': True, 'diagnosis': diag}

    if _scheduler_unhealthy_since is None:
        _scheduler_unhealthy_since = now
    unhealthy_for = now - (_scheduler_unhealthy_since or now)

    if unhealthy_for >= OWNER_UNHEALTHY_SECONDS:
        reason = ','.join(diag.get('issues') or ['unhealthy'])[:120]
        attempt_orchestrator_recovery(reason)

    return {'healthy': False, 'diagnosis': diag, 'unhealthy_for_seconds': int(unhealthy_for)}


def tick_from_scheduler(scheduler_pid: int) -> None:
    """Called from master_scheduler each minute — persist heartbeat only."""
    from backend.orchestration.orchestrator_state import record_scheduler_tick

    record_scheduler_tick(scheduler_pid)
    global _scheduler_unhealthy_since
    _scheduler_unhealthy_since = None

    try:
        from backend.lifecycle.lifecycle_tracing import load_lifecycle_state
        state = load_lifecycle_state()
        if state.get('pipeline_status') == 'COMPLETE':
            from backend.orchestration.orchestrator_state import record_eod_completion
            record_eod_completion(state.get('last_eod_cycle_at'))
            _log('LIFECYCLE VERIFY', 'Brain refreshed successfully')
    except Exception:
        pass
