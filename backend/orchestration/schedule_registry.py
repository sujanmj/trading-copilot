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


def ist_daily(hour: int, minute: int, *, weekdays_only: bool = True, name: Optional[str] = None):
    """Decorator — register a job at HH:MM IST."""

    def decorator(fn: Callable):
        _IST_JOBS.append({
            'name': name or fn.__name__,
            'hour': hour,
            'minute': minute,
            'weekdays_only': weekdays_only,
            'fn': fn,
        })
        _job_runtime_status[name or fn.__name__] = 'registered'
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
        })
    return {
        'scheduler_time_ist': now.strftime('%Y-%m-%d %H:%M:%S IST'),
        'scheduler_weekday': now.strftime('%A'),
        'tasks': tasks,
    }


def dump_task_registry():
    reg = get_task_registry()
    print('[SCHEDULER TASKS]', flush=True)
    for t in reg['tasks']:
        print(f"  {t['name']}: {t['status']} @ {t['schedule']}", flush=True)
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
        print(f"[SCHEDULER IST] Executing {name} @ {now.strftime('%H:%M')} IST", flush=True)
        try:
            job['fn']()
            set_job_status(name, 'completed')
            fired.append(name)
        except Exception as e:
            set_job_status(name, f'failed:{e}')
            print(f"[SCHEDULER IST] {name} FAILED: {e}", flush=True)
            raise
    return fired
