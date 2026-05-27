"""
Frozen snapshot pipeline stage tracing — scanner → aggregation → synthesis →
snapshot export → cache → telegram.

Structured log: backend/logs/pipeline_stages.log
State mirror: data/pipeline_stage_state.json (for /status + stall detection).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR, LOGS_DIR

IST = pytz.timezone('Asia/Kolkata')

STAGES = (
    'scanner',
    'aggregation',
    'synthesis',
    'snapshot_export',
    'cache',
    'telegram',
)

STAGE_SLA_SECONDS = {
    'scanner': 2700,
    'aggregation': 3600,
    'synthesis': 3600,
    'snapshot_export': 1800,
    'cache': 7200,
    'telegram': 7200,
}

_LOG_FILE = LOGS_DIR / 'pipeline_stages.log'
_STATE_FILE = DATA_DIR / 'pipeline_stage_state.json'
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _load_state() -> dict:
    if not _STATE_FILE.exists():
        return {'stages': {}, 'updated_at': None}
    try:
        data = json.loads(_STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'stages': {}, 'updated_at': None}
    except Exception:
        return {'stages': {}, 'updated_at': None}


def pipeline_stage_log(
    stage: str,
    *,
    status: str = 'ok',
    detail: str = '',
    duration_ms: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> dict:
    """Record one pipeline stage completion with IST timestamp."""
    stage = str(stage or '').strip().lower()
    if stage not in STAGES:
        stage = stage or 'unknown'

    now_unix = time.time()
    entry = {
        'at': _now_iso(),
        'at_unix': now_unix,
        'stage': stage,
        'status': status,
        'detail': str(detail or '')[:200],
        'duration_ms': duration_ms,
    }
    if str(status).lower() in ('ok', 'success', 'complete'):
        entry['last_success_at'] = entry['at']
        entry['last_success_unix'] = now_unix
    if extra:
        entry['extra'] = {k: v for k, v in list(extra.items())[:8]}

    line_parts = [entry['at'], f'stage={stage}', f'status={status}']
    if detail:
        line_parts.append(f'detail={entry["detail"]}')
    if duration_ms is not None:
        line_parts.append(f'duration_ms={duration_ms}')
    if extra:
        for k, v in list(extra.items())[:4]:
            line_parts.append(f'{k}={v}')
    line = ' | '.join(line_parts)

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with _lock:
            with open(_LOG_FILE, 'a', encoding='utf-8') as fh:
                fh.write(line + '\n')
    except Exception:
        pass

    try:
        state = _load_state()
        stages = state.setdefault('stages', {})
        prev = stages.get(stage) or {}
        if entry.get('last_success_at'):
            stages[stage] = {**prev, **entry}
        else:
            stages[stage] = {**entry, **{k: v for k, v in prev.items() if k.startswith('last_success')}}
        state['updated_at'] = entry['at']
        state['last_stage'] = stage
        atomic_write_json(_STATE_FILE, state)
    except Exception:
        pass

    try:
        from backend.lifecycle.lifecycle_tracing import pipeline_log
        pipeline_log(f'{stage} {status}' + (f' — {detail[:80]}' if detail else ''), stage=stage)
    except Exception:
        pass

    return entry


def get_pipeline_stage_summary() -> Dict[str, Any]:
    """Return per-stage age and stall hints for runtime_state /status."""
    state = _load_state()
    stages = state.get('stages') or {}
    now = time.time()
    stalled = []
    healthy = []
    rows = {}

    for name in STAGES:
        rec = stages.get(name) or {}
        ts = rec.get('last_success_unix') or rec.get('at_unix')
        sla = STAGE_SLA_SECONDS.get(name, 3600)
        if ts is None:
            rows[name] = {
                'status': 'never',
                'age_minutes': None,
                'stalled': False,
                'last_success_at': None,
            }
            continue
        age_sec = max(0, now - float(ts))
        age_min = int(age_sec / 60)
        is_stalled = age_sec > sla
        rows[name] = {
            'status': rec.get('status', 'ok'),
            'at': rec.get('at'),
            'last_success_at': rec.get('last_success_at') or rec.get('at'),
            'age_minutes': age_min,
            'stalled': is_stalled,
            'detail': rec.get('detail', ''),
        }
        if is_stalled:
            stalled.append(name)
        else:
            healthy.append(name)

    return {
        'stages': rows,
        'stalled_stages': stalled,
        'healthy_stages': healthy,
        'any_stalled': bool(stalled),
        'last_stage': state.get('last_stage'),
        'updated_at': state.get('updated_at'),
    }


def detect_stalled_stages(threshold_minutes: int = 30) -> Dict[str, Any]:
    """Stages with no heartbeat longer than threshold (default 30m)."""
    summary = get_pipeline_stage_summary()
    critical = {'scanner', 'snapshot_export', 'synthesis'}
    overdue = []
    for name, row in (summary.get('stages') or {}).items():
        age = row.get('age_minutes')
        if age is None:
            if name in critical:
                overdue.append({'stage': name, 'reason': 'never_run'})
            continue
        if age >= threshold_minutes:
            overdue.append({'stage': name, 'age_minutes': age, 'reason': 'sla_exceeded'})
    return {
        'overdue': overdue,
        'critical_overdue': [o for o in overdue if o['stage'] in critical],
        'threshold_minutes': threshold_minutes,
    }
