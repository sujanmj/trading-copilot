"""
EOD recovery — catch missed post-market lifecycle after Railway restarts or boot delays.
"""

from __future__ import annotations

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
MAX_EOD_RECOVERY_PER_DAY = int(__import__('os').environ.get('MAX_EOD_RECOVERY_PER_DAY', '3'))


def _now_ist() -> datetime:
    return datetime.now(IST)


def _today() -> str:
    return _now_ist().strftime('%Y-%m-%d')


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

    state = load_lifecycle_state()
    today = _today()

    if state.get('pipeline_status') == 'RUNNING':
        return False, 'pipeline_running'

    try:
        from backend.utils.process_lock import lock_status
        eod_lock = lock_status().get('eod_lifecycle') or {}
        if eod_lock.get('alive'):
            return False, 'eod_lock_held'
    except Exception:
        pass

    complete_today = (
        state.get('last_eod_cycle_date') == today
        and state.get('evaluation_cycle_complete')
        and state.get('pipeline_status') == 'COMPLETE'
    )
    if complete_today:
        return False, 'already_complete_today'

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
