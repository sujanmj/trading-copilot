"""
Lifecycle pipeline tracing — structured logs, error persistence, heartbeat.
"""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any, Optional

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR, LOGS_DIR

IST = pytz.timezone('Asia/Kolkata')
LIFECYCLE_STATE_FILE = DATA_DIR / 'lifecycle_state.json'
LIFECYCLE_ERRORS_FILE = DATA_DIR / 'lifecycle_errors.log'

# Scheduler subprocess uses exit code 75 when singleton guard skips duplicate launch.
SCHEDULER_EXIT_SINGLETON = 75


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def pipeline_log(message: str, *, stage: Optional[str] = None):
    prefix = '[EOD PIPELINE]'
    if stage:
        print(f"{prefix} [{stage}] {message}", flush=True)
    else:
        print(f"{prefix} {message}", flush=True)


def log_error(context: str, exc: BaseException, *, stage: Optional[str] = None):
    """Append full exception to lifecycle_errors.log — never silent."""
    pipeline_log(f"ERROR in {context}: {exc}", stage=stage)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LIFECYCLE_ERRORS_FILE, 'a', encoding='utf-8') as f:
            f.write(f"\n{'=' * 60}\n")
            f.write(f"time={_now_iso()} stage={stage or context}\n")
            f.write(f"error={exc}\n")
            f.write(traceback.format_exc())
            f.write('\n')
    except Exception as log_exc:
        print(f"[EOD PIPELINE] Could not write lifecycle_errors.log: {log_exc}", flush=True)


def load_lifecycle_state(default: Optional[dict] = None) -> dict:
    if default is None:
        default = {}
    if not LIFECYCLE_STATE_FILE.exists():
        return default
    try:
        import json
        with open(LIFECYCLE_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def update_heartbeat(
    *,
    pipeline_status: str,
    current_stage: Optional[str] = None,
    stage_result: Optional[str] = None,
    extra: Optional[dict] = None,
):
    """
    Persist lifecycle heartbeat for OPS / Telegram.
    pipeline_status: IDLE | RUNNING | COMPLETE | FAILED | STALE | RECOVERING
    """
    state = load_lifecycle_state({
        'pipeline_status': 'IDLE',
        'heartbeat_at': None,
        'current_stage': None,
        'last_successful_eod': None,
        'last_evaluation_completion': None,
        'last_stats_export': None,
        'last_history_export': None,
        'last_calibration_export': None,
        'last_journal_generation': None,
        'last_brain_refresh': None,
        'stage_history': [],
    })
    state['pipeline_status'] = pipeline_status
    state['heartbeat_at'] = _now_iso()
    if current_stage:
        state['current_stage'] = current_stage
        history = list(state.get('stage_history') or [])
        history.append({
            'stage': current_stage,
            'result': stage_result or pipeline_status,
            'at': _now_iso(),
        })
        state['stage_history'] = history[-40:]

    if extra:
        state.update(extra)

    atomic_write_json(LIFECYCLE_STATE_FILE, state)
    return state


def mark_stage_complete(stage: str, *, extra_fields: Optional[dict] = None):
    """Record per-stage completion timestamps on lifecycle_state.json."""
    mapping = {
        'evaluate_outcomes': 'last_evaluation_completion',
        'stats_export': 'last_stats_export',
        'history_export': 'last_history_export',
        'calibration_snapshot': 'last_calibration_export',
        'adaptive_calibration': 'last_calibration_export',
        'daily_review': 'last_journal_generation',
        'brain_refresh': 'last_brain_refresh',
        'telegram_daily_review': 'last_journal_generation',
    }
    fields = {}
    key = mapping.get(stage)
    if key:
        fields[key] = _now_iso()
    if extra_fields:
        fields.update(extra_fields)
    update_heartbeat(pipeline_status='RUNNING', current_stage=stage, stage_result='ok', extra=fields)
