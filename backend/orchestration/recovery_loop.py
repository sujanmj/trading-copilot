"""
Lightweight operational self-healing — bounded, market-aware recovery only.

Retained: provider failover (elsewhere), missed EOD replay, stale export refresh,
stale lock cleanup, scheduler thread recovery, lifecycle validation, graceful degradation.

No aggressive autonomous restart storms or nested recovery loops.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz

from backend.orchestration.eod_recovery import is_post_market_weekday
from backend.orchestration.orchestrator_state import (
    MODE_API_ONLY,
    MODE_PRIMARY,
    MODE_RECOVERING,
    OWNER_UNHEALTHY_SECONDS,
    bootstrap_api_runtime,
    load_orchestrator_state,
    mark_api_only,
    record_recovery_attempt,
    refresh_component_snapshot,
    save_orchestrator_state,
    set_mode,
    validate_singleton_ownership,
)
from backend.utils.config import DATA_DIR, IS_LOCAL_DEV

IST = pytz.timezone('Asia/Kolkata')

HEALTH_TICK_SECONDS = 60
RECOVERY_COOLDOWN_SECONDS = int(os.environ.get('ORCHESTRATOR_RECOVERY_COOLDOWN', '900'))  # 15 min
MAX_RECOVERY_PER_HOUR = int(os.environ.get('ORCHESTRATOR_MAX_RECOVERY_HOUR', '4'))
PARTIAL_REPLAY_COOLDOWN_SECONDS = int(os.environ.get('PARTIAL_REPLAY_COOLDOWN', '900'))
MAX_PARTIAL_REPLAY_PER_SESSION = 1
SCHEDULER_RETRY_BACKOFF_SECONDS = int(os.environ.get('SCHEDULER_RETRY_BACKOFF', '30'))
NIGHT_TICK_DEAD_SECONDS = 600

_recovery_lock = threading.Lock()
_recovery_in_progress = False
_last_health_tick = 0.0
_last_recovery_at = 0.0
_recovery_hour_bucket = ''
_recovery_hour_count = 0
_scheduler_unhealthy_since: Optional[float] = None
_force_scheduler_retry = threading.Event()
_partial_replay_session_date = ''
_partial_replay_count = 0
_last_partial_replay_at = 0.0


def _log(tag: str, message: str):
    print(f"[{tag}] {message}", flush=True)


def _operational_context() -> dict:
    try:
        from backend.utils.market_hours import get_operational_status
        return get_operational_status()
    except Exception:
        return {'expect_quiet_collectors': False, 'market_hours': True}


def _quiet_period() -> bool:
    return bool(_operational_context().get('expect_quiet_collectors'))


def request_scheduler_retry():
    """Signal scheduler subprocess loop to retry after bounded backoff."""
    _force_scheduler_retry.set()


def should_force_scheduler_retry() -> bool:
    if _force_scheduler_retry.is_set():
        _force_scheduler_retry.clear()
        return True
    return False


def scheduler_retry_backoff_seconds() -> int:
    return SCHEDULER_RETRY_BACKOFF_SECONDS


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
    if IS_LOCAL_DEV:
        return
    os.environ.setdefault('WEB_CONCURRENCY', '1')
    os.environ.pop('UVICORN_WORKERS', None)
    dupes = detect_duplicate_workers()
    if dupes:
        _log('ORCHESTRATOR', f'duplicate runtime signals: {", ".join(dupes)}')
        if 'scheduler_disabled' not in dupes:
            _log('ORCHESTRATOR', 'forcing WEB_CONCURRENCY=1 for singleton orchestrator')


def safe_clear_stale_locks(reason: str = 'lightweight_recovery') -> bool:
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

    quiet = _quiet_period()
    if not quiet:
        try:
            from backend.lifecycle.prediction_lifecycle_engine import get_lifecycle_status
            lc = get_lifecycle_status()
            if lc.get('pipeline_status') == 'STALE':
                issues.append('lifecycle_stale')
            if lc.get('pipeline_status') == 'COMPLETE' and not lc.get('exports_fresh'):
                issues.append('exports_stale_after_eod')
            if lc.get('pipeline_status') == 'FAILED':
                issues.append('lifecycle_failed')
        except Exception as e:
            issues.append(f'lifecycle_check_error:{e}')

    return {
        'healthy': ownership.get('healthy') and 'no_valid_orchestrator' not in issues,
        'ownership': ownership,
        'issues': issues,
        'mode': state.get('orchestrator_mode'),
        'tick_age_seconds': tick_age,
        'quiet_period': quiet,
    }


def verify_lifecycle_exports() -> Dict[str, Any]:
    """Check post-EOD artifacts; return missing components."""
    if _quiet_period():
        return {'ok': True, 'missing': [], 'skipped': 'quiet_period'}

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


def _is_export_only_gap(missing: List[str]) -> bool:
    export_markers = (
        'stats_', 'history_', 'calibration_',
        'stage_not_marked:stats', 'stage_not_marked:history',
    )
    return bool(missing) and all(
        any(m.startswith(p) or p in m for p in export_markers)
        for m in missing
    )


def _try_export_only_replay(missing: List[str]) -> bool:
    """Rerun export stages only — no full EOD replay."""
    if not _is_export_only_gap(missing):
        return False
    _log('ORCHESTRATOR', f'export-only replay — {", ".join(missing[:5])}')
    try:
        from backend.orchestration.master_scheduler import run_standalone_script
        if any('stats' in m for m in missing):
            run_standalone_script('stats_exporter.py')
        if any('history' in m for m in missing):
            run_standalone_script('history_exporter.py')
        record_recovery_attempt('export_only_replay', 'triggered', detail=','.join(missing[:8]))
        return True
    except Exception as e:
        record_recovery_attempt('export_only_replay', 'failed', detail=str(e))
        _log('ORCHESTRATOR', f'export-only replay failed: {e}')
        return False


def trigger_partial_lifecycle_replay(missing: List[str]) -> bool:
    """Replay missed EOD once per session — bounded cooldown, export-only when possible."""
    global _partial_replay_session_date, _partial_replay_count, _last_partial_replay_at

    if not missing or not is_post_market_weekday():
        return False

    today = datetime.now(IST).strftime('%Y-%m-%d')
    if _partial_replay_session_date != today:
        _partial_replay_session_date = today
        _partial_replay_count = 0

    now = time.time()
    if _partial_replay_count >= MAX_PARTIAL_REPLAY_PER_SESSION:
        return False
    if now - _last_partial_replay_at < PARTIAL_REPLAY_COOLDOWN_SECONDS:
        return False

    if _recovery_in_progress:
        return False

    if _try_export_only_replay(missing):
        _last_partial_replay_at = now
        _partial_replay_count += 1
        return True

    _log('ORCHESTRATOR', f'missed EOD replay (once/session) — {", ".join(missing[:5])}')
    set_mode(MODE_RECOVERING, reason='partial_lifecycle_replay')
    try:
        from backend.orchestration.master_scheduler import run_post_market_pipeline
        run_post_market_pipeline(force=True, trigger='recovery:partial_replay')
        record_recovery_attempt('partial_lifecycle_replay', 'triggered', detail=','.join(missing[:8]))
        _last_partial_replay_at = now
        _partial_replay_count += 1
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
    elif not _quiet_period():
        _log('GUI SYNC', f'stale — scheduler={scheduler.get("status")} lifecycle={lifecycle.get("pipeline_status")}')
    return {'validated': validated, 'components': components}


def _recovery_allowed(diag: Dict[str, Any]) -> bool:
    """Market-aware gate — quiet hours only recover on real failures."""
    if not _quiet_period():
        return True
    issues = diag.get('issues') or []
    if 'no_valid_orchestrator' in issues or 'scheduler_disabled' in issues:
        return True
    if 'lifecycle_failed' in issues:
        return True
    tick_age = diag.get('tick_age_seconds')
    if tick_age is not None and tick_age >= NIGHT_TICK_DEAD_SECONDS:
        return True
    for issue in issues:
        if issue.startswith('orchestrator_unhealthy:') and tick_age is not None and tick_age >= NIGHT_TICK_DEAD_SECONDS:
            return True
    return False


def attempt_orchestrator_recovery(reason: str, diag: Optional[Dict[str, Any]] = None) -> bool:
    """Clear stale locks and signal a single scheduler relaunch — bounded cooldown."""
    if IS_LOCAL_DEV:
        return False

    diag = diag or diagnose_runtime()
    if not _recovery_allowed(diag):
        _log('ORCHESTRATOR', 'recovery skipped — quiet period (no critical failure)')
        return False

    global _last_recovery_at, _recovery_in_progress

    now = time.time()
    with _recovery_lock:
        if _recovery_in_progress:
            return False
        if now - _last_recovery_at < RECOVERY_COOLDOWN_SECONDS:
            _log('ORCHESTRATOR', f'recovery cooldown active ({RECOVERY_COOLDOWN_SECONDS}s)')
            return False

        hour_key = datetime.now(IST).strftime('%Y-%m-%d-%H')
        global _recovery_hour_bucket, _recovery_hour_count
        if _recovery_hour_bucket != hour_key:
            _recovery_hour_bucket = hour_key
            _recovery_hour_count = 0
        if _recovery_hour_count >= MAX_RECOVERY_PER_HOUR:
            _log('ORCHESTRATOR', 'recovery rate limited — max attempts this hour')
            return False

        _recovery_in_progress = True
        try:
            set_mode(MODE_RECOVERING, reason=reason)
            cleared = safe_clear_stale_locks(reason)
            request_scheduler_retry()
            _last_recovery_at = now
            _recovery_hour_count += 1
            record_recovery_attempt(reason, 'recovery_triggered', detail=f'lock_cleared={cleared}')
            return True
        finally:
            _recovery_in_progress = False


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
        if tick_age is None and not _quiet_period():
            safe_clear_stale_locks('singleton_exit_no_heartbeat')
            return 'retry_immediate'
        return 'wait_primary'

    return 'wait_primary'


def bootstrap_self_healing(api_pid: Optional[int] = None) -> dict:
    if IS_LOCAL_DEV:
        from backend.utils.local_runtime import local_log
        local_log('LOCAL RUNTIME', 'cloud recovery disabled in LOCAL_DEV_MODE')
        return load_orchestrator_state()
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
    _log('ORCHESTRATOR', 'lightweight self-healing bootstrap complete')
    return refresh_component_snapshot()


def run_orchestrator_health_tick() -> Dict[str, Any]:
    """60s health verification — calm, bounded recovery only."""
    if IS_LOCAL_DEV:
        return {'healthy': True, 'local_dev': True, 'skipped': True}
    global _last_health_tick, _scheduler_unhealthy_since

    now = time.time()
    if now - _last_health_tick < HEALTH_TICK_SECONDS - 5:
        return {'skipped': True}
    _last_health_tick = now

    diag = diagnose_runtime()
    snap = refresh_component_snapshot()

    if diag.get('healthy'):
        _scheduler_unhealthy_since = None
        if snap.get('orchestrator_mode') == MODE_RECOVERING:
            set_mode(MODE_PRIMARY, reason='health_tick_ok')
        elif snap.get('orchestrator_mode') != MODE_API_ONLY:
            set_mode(MODE_PRIMARY, reason='health_tick_ok')

        missing = verify_lifecycle_exports()
        if not missing.get('ok') and is_post_market_weekday():
            trigger_partial_lifecycle_replay(missing.get('missing') or [])

        if not _quiet_period():
            verify_gui_sync()
        return {'healthy': True, 'diagnosis': diag}

    if _scheduler_unhealthy_since is None:
        _scheduler_unhealthy_since = now
    unhealthy_for = now - (_scheduler_unhealthy_since or now)

    if unhealthy_for >= OWNER_UNHEALTHY_SECONDS:
        reason = ','.join(diag.get('issues') or ['unhealthy'])[:120]
        attempt_orchestrator_recovery(reason, diag)

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
