"""
IST-aware daily job registry + task visibility for master scheduler.
The `schedule` library uses host local time — on UTC hosts (Railway) 15:45 IST
would never fire at 15:45. Daily jobs register here and tick in IST.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import pytz

IST = pytz.timezone('Asia/Kolkata')

_IST_JOBS: List[dict] = []
_ist_last_fired: Dict[str, float] = {}
_job_runtime_status: Dict[str, str] = {}
_last_tick_log_minute: str | None = None
_PRIMARY_SCHEDULER_BOUND = False

# Sub-stages executed inside eod_lifecycle @ 15:45 IST (visibility only)
EOD_PIPELINE_TASKS = [
    {'name': 'stats_export', 'schedule': '15:45 IST (inside eod_lifecycle)', 'parent': 'eod_lifecycle'},
    {'name': 'history_export', 'schedule': '15:45 IST (inside eod_lifecycle)', 'parent': 'eod_lifecycle'},
    {'name': 'calibration_snapshot', 'schedule': '15:45 IST (inside eod_lifecycle)', 'parent': 'eod_lifecycle'},
    {'name': 'daily_review', 'schedule': '15:45 IST (inside eod_lifecycle)', 'parent': 'eod_lifecycle'},
]


def bind_primary_scheduler() -> bool:
    """Mark this process as the sole IST job registry owner (singleton scheduler)."""
    global _PRIMARY_SCHEDULER_BOUND
    if _PRIMARY_SCHEDULER_BOUND:
        return False
    _PRIMARY_SCHEDULER_BOUND = True
    return True


def is_primary_scheduler() -> bool:
    return _PRIMARY_SCHEDULER_BOUND


def ist_daily(hour: int, minute: int, *, weekdays_only: bool = True, name: Optional[str] = None):
    """Decorator — register a job at HH:MM IST."""

    def decorator(fn: Callable):
        job_name = name or fn.__name__
        if any(j['name'] == job_name for j in _IST_JOBS):
            return fn
        _IST_JOBS.append({
            'name': job_name,
            'hour': hour,
            'minute': minute,
            'weekdays_only': weekdays_only,
            'fn': fn,
        })
        _job_runtime_status[job_name] = 'registered'
        return fn

    return decorator


def set_job_status(name: str, status: str):
    _job_runtime_status[name] = status


def get_task_registry() -> dict:
    now = datetime.now(IST)
    tasks = []
    for job in _IST_JOBS:
        name = job['name']
        tasks.append({
            'name': name,
            'schedule': f"{job['hour']:02d}:{job['minute']:02d} IST",
            'weekdays_only': job['weekdays_only'],
            'status': _job_runtime_status.get(name, 'registered'),
            'kind': 'ist_daily',
        })
    for pt in EOD_PIPELINE_TASKS:
        tasks.append({
            'name': pt['name'],
            'schedule': pt['schedule'],
            'weekdays_only': True,
            'status': _job_runtime_status.get('eod_lifecycle', 'registered'),
            'kind': 'eod_pipeline',
            'parent': pt.get('parent'),
        })
    return {
        'scheduler_time_ist': now.strftime('%Y-%m-%d %H:%M:%S IST'),
        'scheduler_weekday': now.strftime('%A'),
        'primary_scheduler': _PRIMARY_SCHEDULER_BOUND,
        'tasks': tasks,
    }


def log_scheduler_tick():
    """Once-per-minute heartbeat so Railway logs prove the scheduler loop is alive."""
    global _last_tick_log_minute
    now = datetime.now(IST)
    minute_key = now.strftime('%Y-%m-%d %H:%M')
    if _last_tick_log_minute == minute_key:
        return
    _last_tick_log_minute = minute_key
    eod = next((j for j in _IST_JOBS if j['name'] == 'eod_lifecycle'), None)
    eod_at = f"{eod['hour']:02d}:{eod['minute']:02d} IST" if eod else 'missing'
    print(
        f"[SCHEDULER TICK] {now.strftime('%H:%M:%S IST')} "
        f"jobs={len(_IST_JOBS)} eod_lifecycle@{eod_at} primary={_PRIMARY_SCHEDULER_BOUND}",
        flush=True,
    )
    try:
        import os
        if os.environ.get('LOCAL_DEV_MODE') == '1':
            return
        from backend.orchestration.recovery_loop import tick_from_scheduler
        tick_from_scheduler(os.getpid())
    except Exception as e:
        print(f"[ORCHESTRATOR] tick persist failed: {e}", flush=True)


def dump_task_registry():
    reg = get_task_registry()
    print('[SCHEDULER TASKS]', flush=True)
    for t in reg['tasks']:
        kind = t.get('kind', 'ist_daily')
        if kind == 'eod_pipeline':
            print(f"  * {t['name']} @ {t['schedule']} (via {t.get('parent', 'eod_lifecycle')})", flush=True)
        else:
            print(f"  * {t['name']} @ {t['schedule']} — {t['status']}", flush=True)
    return reg


def tick_ist_jobs() -> List[str]:
    """Fire due IST daily jobs once per minute. Returns names fired."""
    now = datetime.now(IST)
    if now.weekday() >= 5:
        weekday_ok = False
    else:
        weekday_ok = True

    fired = []
    minute_key = now.strftime('%Y-%m-%d %H:%M')

    for job in _IST_JOBS:
        if job['weekdays_only'] and not weekday_ok:
            continue
        if now.hour != job['hour'] or now.minute != job['minute']:
            continue

        fired_key = f"{job['name']}:{minute_key}"
        if fired_key in _ist_last_fired:
            continue
        _ist_last_fired[fired_key] = now.timestamp()

        name = job['name']
        set_job_status(name, 'running')
        if name == 'eod_lifecycle':
            print(f"[EOD TASK FIRING] scheduled @ {now.strftime('%H:%M')} IST", flush=True)
        else:
            print(f"[SCHEDULER IST] Executing {name} @ {now.strftime('%H:%M')} IST", flush=True)
        try:
            job['fn']()
            set_job_status(name, 'completed')
            if name == 'eod_lifecycle':
                print(f"[EOD TASK FIRING] lifecycle thread dispatched @ {now.strftime('%H:%M')} IST", flush=True)
            fired.append(name)
        except Exception as e:
            set_job_status(name, f'failed:{e}')
            print(f"[SCHEDULER IST] {name} FAILED: {e}", flush=True)
            raise
    return fired
