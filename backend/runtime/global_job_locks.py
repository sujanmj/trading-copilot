"""
Centralized runtime job locks + timeout guards for heavy command execution.

Prevents overlapping brain/scanner/aggregation jobs and ensures locks always release.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, Optional, TypeVar

T = TypeVar('T')

DEFAULT_TIMEOUT_SEC = float(os.environ.get('JOB_LOCK_TIMEOUT_SEC', '45'))

GLOBAL_JOB_LOCKS: Dict[str, bool] = {
    'brain': False,
    'scanner': False,
    'aggregation': False,
    'telegram': False,
    'brief': False,
}

_registry_lock = threading.Lock()
_acquire_meta: Dict[str, Dict[str, Any]] = {}
_hold_counts: Dict[str, int] = {}
_logger = logging.getLogger(__name__)


def _log_job_event(event: str, job: str, detail: str = '') -> None:
    ts = datetime.now(timezone.utc).isoformat()
    line = f'{ts} | {event} | job={job} | {detail}\n'
    try:
        from backend.utils.config import DATA_DIR
        log_path = DATA_DIR / 'logs' / 'job_locks.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as fh:
            fh.write(line)
    except Exception:
        pass
    _logger.info('%s job=%s %s', event, job, detail)


def is_job_locked(job: str) -> bool:
    with _registry_lock:
        return bool(GLOBAL_JOB_LOCKS.get(job))


def try_acquire_job(job: str, *, owner: str = '') -> bool:
    tid = threading.get_ident()
    with _registry_lock:
        if GLOBAL_JOB_LOCKS.get(job):
            held = _acquire_meta.get(job) or {}
            if held.get('thread') == tid:
                _hold_counts[job] = _hold_counts.get(job, 1) + 1
                _log_job_event('lock_reentrant', job, f'owner={owner} depth={_hold_counts[job]}')
                return True
            _log_job_event(
                'lock_denied',
                job,
                f'owner={owner} duplicate_suppressed held_by={held.get("owner", "?")}',
            )
            return False
        GLOBAL_JOB_LOCKS[job] = True
        _hold_counts[job] = 1
        _acquire_meta[job] = {'owner': owner, 'at': time.time(), 'thread': tid}
        _log_job_event('lock_acquired', job, f'owner={owner}')
        return True


def release_job(job: str, *, owner: str = '') -> None:
    tid = threading.get_ident()
    with _registry_lock:
        held = _acquire_meta.get(job) or {}
        if held.get('thread') != tid and GLOBAL_JOB_LOCKS.get(job):
            _log_job_event('lock_release_skip', job, f'owner={owner} foreign_thread')
            return
        depth = _hold_counts.get(job, 1) - 1
        if depth > 0:
            _hold_counts[job] = depth
            _log_job_event('lock_reentrant_release', job, f'owner={owner} depth={depth}')
            return
        GLOBAL_JOB_LOCKS[job] = False
        _acquire_meta.pop(job, None)
        _hold_counts.pop(job, None)
        _log_job_event('lock_released', job, f'owner={owner}')


@contextmanager
def job_guard(job: str, *, owner: str = '') -> Iterator[bool]:
    acquired = try_acquire_job(job, owner=owner)
    try:
        yield acquired
    finally:
        if acquired:
            release_job(job, owner=owner)


def duplicate_job_message(job: str) -> str:
    messages = {
        'brain': '🧠 Analysis already running...',
        'brief': '⏳ Brief generation already running...',
        'scanner': '⏳ Scanner job already running...',
        'aggregation': '⏳ Aggregation already running...',
        'telegram': '⏳ Telegram dispatch already running...',
    }
    return messages.get(job, '⏳ Job already running...')


def run_with_timeout(
    fn: Callable[[], T],
    *,
    job: str = '',
    timeout: float = DEFAULT_TIMEOUT_SEC,
    owner: str = '',
) -> T:
    """Run synchronous work in a worker thread with a hard timeout."""
    label = job or 'anonymous'
    _log_job_event('job_start', label, f'timeout={timeout}s owner={owner}')
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        try:
            result = future.result(timeout=timeout)
            _log_job_event('job_finish', label, f'elapsed={time.time() - started:.1f}s owner={owner}')
            return result
        except concurrent.futures.TimeoutError as exc:
            _log_job_event('job_timeout', label, f'timeout={timeout}s owner={owner}')
            raise TimeoutError(f'{label} timed out after {timeout}s') from exc


async def await_with_timeout(
    coro,
    *,
    job: str = '',
    timeout: float = DEFAULT_TIMEOUT_SEC,
):
    """Async helper — asyncio.wait_for with structured logging."""
    label = job or 'async'
    _log_job_event('job_start', label, f'timeout={timeout}s async=1')
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        _log_job_event('job_finish', label, 'async=1')
        return result
    except asyncio.TimeoutError as exc:
        _log_job_event('job_timeout', label, f'timeout={timeout}s async=1')
        raise TimeoutError(f'{label} timed out after {timeout}s') from exc


def load_committed_snapshot_dict() -> Optional[dict]:
    """Load last committed market snapshot JSON (for API degraded fallback)."""
    try:
        from backend.utils.config import CURRENT_SNAPSHOT_FILE
        if not CURRENT_SNAPSHOT_FILE.exists():
            return None
        return json.loads(CURRENT_SNAPSHOT_FILE.read_text(encoding='utf-8'))
    except Exception:
        return None
