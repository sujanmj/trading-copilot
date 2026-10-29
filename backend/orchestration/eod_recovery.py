"""
EOD recovery — catch missed post-market lifecycle after Railway restarts or boot delays.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, time as dt_time
from typing import Tuple

import pytz

IST = pytz.timezone('Asia/Kolkata')

EOD_HOUR = 15
EOD_MINUTE = 45
RECOVERY_COOLDOWN_SECONDS = 300
_last_recovery_attempt = 0.0
_eod_recovery_day = ''
_eod_recovery_count = 0
MAX_EOD_RECOVERY_PER_DAY = int(os.environ.get('MAX_EOD_RECOVERY_PER_DAY', '3'))
EOD_STALE_RUNNING_SECONDS = int(os.environ.get('EOD_STALE_RUNNING_SECONDS', '2700'))


def _now_ist() -> datetime:
    return datetime.now(IST)


def _today() -> str:
    return _now_ist().strftime('%Y-%m-%d')


def get_stale_running_details(state: dict, now: datetime | None = None) -> dict:
    """Describe an EOD RUNNING heartbeat that has stopped advancing."""
    if str(state.get('pipeline_status') or '').upper() != 'RUNNING':
        return {'stale': False}
    now = now or _now_ist()
    if now.tzinfo is None:
        now = IST.localize(now)
    else:
        now = now.astimezone(IST)
    raw = state.get('heartbeat_at') or state.get('last_eod_attempt_at')
    if not raw:
        # Without a timestamp we cannot distinguish a live run from an old one.
        return {'stale': False, 'reason': 'missing_progress_timestamp'}
    try:
        heartbeat = datetime.fromisoformat(str(raw))
        if heartbeat.tzinfo is None:
            heartbeat = IST.localize(heartbeat)
        age_seconds = max(0, int((now - heartbeat.astimezone(IST)).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return {'stale': False, 'reason': 'invalid_progress_timestamp'}
    return {
        'stale': age_seconds > EOD_STALE_RUNNING_SECONDS,
        'age_seconds': age_seconds,
        'stage': str(state.get('current_stage') or 'unknown'),
        'threshold_seconds': EOD_STALE_RUNNING_SECONDS,
    }


def reconcile_orphaned_history_export_status(now: datetime | None = None) -> bool:
    """Close a stale RUNNING marker written by the former standalone exporter.

    Only reconcile when the EOD itself is recorded complete, a history export
    succeeded after it, and the EOD single-execution lock can be acquired.
    This repairs persisted state left by older releases without replaying
    prediction outcomes.
    """
    from backend.lifecycle.lifecycle_tracing import load_lifecycle_state, update_heartbeat
    from backend.history.history_engine import get_history_heartbeat

    now = now or _now_ist()
    if now.tzinfo is None:
        now = IST.localize(now)
    else:
        now = now.astimezone(IST)
    state = load_lifecycle_state()
    progress = get_stale_running_details(state, now)
    if (
        not progress.get('stale')
        or progress.get('stage') != 'history_export'
        or not state.get('evaluation_cycle_complete')
    ):
        return False

    def _parse_timestamp(value: object) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is None:
                parsed = IST.localize(parsed)
            return parsed.astimezone(IST)
        except (TypeError, ValueError, OverflowError):
            return None

    completed_at = _parse_timestamp(state.get('last_successful_eod'))
    if (
        completed_at is None
        or str(state.get('last_eod_cycle_date') or '') != completed_at.strftime('%Y-%m-%d')
    ):
        return False

    history = get_history_heartbeat()
    history_completed_at = _parse_timestamp(history.get('last_successful_history'))
    history_heartbeat = _parse_timestamp(history.get('heartbeat_at'))
    if (
        str(history.get('status') or '').lower() != 'ok'
        or history_completed_at is None
        or history_heartbeat is None
        or history_completed_at < completed_at
    ):
        return False

    from backend.utils.process_lock import release_lock, try_acquire_lock

    if not try_acquire_lock('eod_lifecycle'):
        return False
    try:
        # The lock closes the race with a newly-started EOD. Recheck the state
        # after acquiring it before replacing the old heartbeat.
        current = load_lifecycle_state()
        if (
            current.get('pipeline_status') != 'RUNNING'
            or current.get('current_stage') != 'history_export'
            or current.get('heartbeat_at') != state.get('heartbeat_at')
            or not current.get('evaluation_cycle_complete')
        ):
            return False
        update_heartbeat(
            pipeline_status='COMPLETE',
            current_stage='completed',
            stage_result='orphaned_history_export_reconciled',
            extra={'history_export_status_reconciled_at': now.isoformat()},
        )
        print('[EOD RECOVERY] Reconciled stale standalone history-export heartbeat', flush=True)
        return True
    finally:
        release_lock('eod_lifecycle')


def is_post_market_weekday(now: datetime | None = None) -> bool:
    """True on Mon–Fri at or after 15:45 IST."""
    now = now or _now_ist()
    if now.weekday() >= 5:
        return False
    return now.time() >= dt_time(EOD_HOUR, EOD_MINUTE)


def needs_eod_recovery(now: datetime | None = None) -> Tuple[bool, str]:
    """
    True when post-market window has started but today's EOD has not completed.
    """
    now = now or _now_ist()
    if not is_post_market_weekday(now):
        return False, 'before_post_market_window'

    from backend.lifecycle.prediction_lifecycle_engine import load_lifecycle_state

    reconcile_orphaned_history_export_status(now)

    state = load_lifecycle_state()
    today = _today()

    complete_today = (
        state.get('last_eod_cycle_date') == today
        and state.get('evaluation_cycle_complete')
        and state.get('pipeline_status') == 'COMPLETE'
    )
    if complete_today:
        return False, 'already_complete_today'

    if state.get('pipeline_status') == 'RUNNING':
        progress = get_stale_running_details(state, now)
        if not progress.get('stale'):
            return False, 'pipeline_running'
        try:
            from backend.utils.process_lock import lock_status
            eod_lock = lock_status().get('eod_lifecycle') or {}
        except Exception:
            # Fail closed: never start a second EOD cycle if lock ownership is unknown.
            return False, 'stale_pipeline_lock_status_unavailable'
        if eod_lock.get('valid'):
            return False, f"stale_pipeline_owner_alive:{progress['stage']}:{progress['age_seconds']}s"
        return True, f"stale_pipeline_recovery:{progress['stage']}:{progress['age_seconds']}s"

    try:
        from backend.utils.process_lock import lock_status
        eod_lock = lock_status().get('eod_lifecycle') or {}
        if eod_lock.get('valid'):
            return False, 'eod_lock_held'
    except Exception:
        pass

    return True, 'missed_or_incomplete_eod'


def maybe_trigger_eod_recovery(reason: str, *, force: bool = False) -> bool:
    """
    Trigger run_post_market_pipeline(force=True) when EOD was missed.
    Returns True if recovery was started.
    """
    global _last_recovery_attempt, _eod_recovery_day, _eod_recovery_count

    should, why = needs_eod_recovery()
    if not should:
        if force:
            print(f"[EOD RECOVERY] Skip ({why})", flush=True)
        return False

    today = _today()
    if _eod_recovery_day != today:
        _eod_recovery_day = today
        _eod_recovery_count = 0
    if _eod_recovery_count >= MAX_EOD_RECOVERY_PER_DAY:
        print(f"[EOD RECOVERY] Daily limit reached ({MAX_EOD_RECOVERY_PER_DAY})", flush=True)
        return False

    now = time.time()
    if now - _last_recovery_attempt < RECOVERY_COOLDOWN_SECONDS:
        return False
    _last_recovery_attempt = now
    _eod_recovery_count += 1

    print(
        f"[EOD RECOVERY] Triggering missed EOD — reason={reason} detail={why} "
        f"@ {_now_ist().strftime('%H:%M:%S IST')}",
        flush=True,
    )

    try:
        from backend.lifecycle.lifecycle_tracing import update_heartbeat
        update_heartbeat(
            pipeline_status='RECOVERING',
            current_stage='startup_recovery',
            extra={'recovery_reason': reason, 'recovery_detail': why},
        )
    except Exception as e:
        print(f"[EOD RECOVERY] Heartbeat update failed: {e}", flush=True)

    from backend.orchestration.master_scheduler import run_post_market_pipeline

    run_post_market_pipeline(force=True, trigger=f'recovery:{reason}')
    return True


def run_startup_eod_recovery():
    """Called once when primary scheduler acquires lock — replay missed EOD if needed."""
    should, why = needs_eod_recovery()
    if not should:
        print(f"[EOD RECOVERY] Startup check — no recovery needed ({why})", flush=True)
        return
    maybe_trigger_eod_recovery('startup', force=True)
