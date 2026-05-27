"""Durable retry queue for failed pipeline stages."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
QUEUE_FILE = DATA_DIR / 'retry_queue.json'
MAX_ATTEMPTS = 5


def _load_queue() -> dict:
    if not QUEUE_FILE.exists():
        return {'jobs': []}
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'jobs': []}
    except Exception:
        return {'jobs': []}


def enqueue_failed_task(stage: str, payload: Optional[dict] = None, *, delay_minutes: int = 15) -> str:
    job_id = str(uuid.uuid4())[:12]
    job = {
        'id': job_id,
        'stage': stage,
        'payload': payload or {},
        'attempts': 0,
        'created_at': datetime.now(IST).isoformat(),
        'next_run_at': (datetime.now(IST) + timedelta(minutes=delay_minutes)).isoformat(),
    }
    data = _load_queue()
    jobs = list(data.get('jobs') or [])
    jobs.append(job)
    data['jobs'] = jobs[-100:]
    atomic_write_json(QUEUE_FILE, data)
    return job_id


def drain_retry_queue(handlers: Dict[str, Callable[[dict], Any]]) -> List[dict]:
    """Process due jobs with registered stage handlers."""
    data = _load_queue()
    jobs = list(data.get('jobs') or [])
    now = datetime.now(IST)
    remaining = []
    results = []
    for job in jobs:
        next_run = job.get('next_run_at')
        try:
            due = datetime.fromisoformat(str(next_run))
            if due.tzinfo is None:
                due = IST.localize(due)
        except Exception:
            due = now
        if due > now.astimezone(IST):
            remaining.append(job)
            continue
        stage = job.get('stage')
        handler = handlers.get(stage)
        if not handler:
            remaining.append(job)
            continue
        job['attempts'] = int(job.get('attempts') or 0) + 1
        try:
            out = handler(job.get('payload') or {})
            results.append({'id': job.get('id'), 'stage': stage, 'status': 'ok', 'result': out})
        except Exception as exc:
            if job['attempts'] >= MAX_ATTEMPTS:
                results.append({'id': job.get('id'), 'stage': stage, 'status': 'failed', 'error': str(exc)})
            else:
                job['next_run_at'] = (now + timedelta(minutes=15 * job['attempts'])).isoformat()
                remaining.append(job)
                results.append({'id': job.get('id'), 'stage': stage, 'status': 'retry', 'error': str(exc)})
    data['jobs'] = remaining
    atomic_write_json(QUEUE_FILE, data)
    return results
