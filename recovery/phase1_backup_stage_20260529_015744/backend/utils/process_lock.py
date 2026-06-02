"""
Cross-platform process locks — prevent duplicate schedulers / analyzers.

Railway note: lock files persist on volumes. After container restart, PID reuse
(e.g. new uvicorn also pid=1) can falsely appear as a live scheduler holder.
We validate /proc/pid/cmdline on Linux before treating a lock as active.
"""

from __future__ import annotations

import json
import os
import sys
import atexit
import time
from pathlib import Path
from typing import Any, Dict, Optional

from backend.utils.config import LOCKS_DIR, ensure_dirs, IS_LOCAL_DEV

_active_locks: list[Path] = []

_LOCK_MAX_AGE_SECONDS = 86400  # 24h — stale lock file age fallback


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == 'win32':
        import subprocess
        result = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}'],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        return str(pid) in (result.stdout or '')
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _proc_cmdline(pid: int) -> str:
    if sys.platform == 'win32':
        return ''
    try:
        raw = Path(f'/proc/{pid}/cmdline').read_bytes()
        return raw.replace(b'\x00', b' ').decode('utf-8', errors='ignore').lower()
    except OSError:
        return ''


def _read_lock_file(lock_path: Path) -> Optional[Dict[str, Any]]:
    if not lock_path.exists():
        return None
    try:
        raw = lock_path.read_text(encoding='utf-8').strip()
        if not raw:
            return None
        if raw.startswith('{'):
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        return {'pid': int(raw), 'script': lock_path.stem, 'started_at': None}
    except (ValueError, OSError, json.JSONDecodeError):
        return None


def _cmdline_matches_lock(name: str, cmdline: str) -> bool:
    if not cmdline:
        # Linux: empty cmdline means we cannot prove ownership — treat as stale.
        # Windows: no /proc; fall back to pid-only check.
        return sys.platform == 'win32'
    if name == 'master_scheduler':
        return (
            'master_scheduler' in cmdline
            or 'orchestration.master_scheduler' in cmdline
            or 'backend/master_scheduler.py' in cmdline
        )
    if name == 'eod_lifecycle':
        return (
            'lifecycle' in cmdline
            or 'prediction_lifecycle' in cmdline
            or 'master_scheduler' in cmdline
        )
    return name.replace('_', '') in cmdline.replace('_', '')


def is_lock_holder_valid(name: str, info: Optional[Dict[str, Any]] = None) -> bool:
    """True only if lock file points to a live process that owns this lock."""
    if IS_LOCAL_DEV:
        return False
    lock_path = LOCKS_DIR / f'{name}.lock'
    if info is None:
        info = _read_lock_file(lock_path)
    if not info:
        return False

    pid = info.get('pid')
    if not isinstance(pid, int) or not _pid_alive(pid):
        return False

    # Railway/Docker: uvicorn is PID 1; scheduler is always a child subprocess.
    if sys.platform != 'win32' and name == 'master_scheduler' and pid == 1:
        return False

    if sys.platform != 'win32':
        cmdline = _proc_cmdline(pid)
        if cmdline and not _cmdline_matches_lock(name, cmdline):
            return False

    started = info.get('started_at')
    if started is not None:
        try:
            if time.time() - float(started) > _LOCK_MAX_AGE_SECONDS:
                return False
        except (TypeError, ValueError):
            pass

    return True


def force_clear_lock(name: str, reason: str = 'orchestrator_recovery') -> bool:
    """Remove lock when heartbeat proves ownership is stale (self-healing)."""
    ensure_dirs()
    lock_path = LOCKS_DIR / f'{name}.lock'
    if not lock_path.exists():
        return False
    try:
        lock_path.unlink(missing_ok=True)
        print(f"[LOCK] Force cleared {name}: {reason}", flush=True)
        return True
    except OSError as e:
        print(f"[LOCK] Could not force clear {name}: {e}", flush=True)
        return False


def clear_stale_lock(name: str) -> bool:
    """Remove lock file when holder is dead or PID was reused by wrong process."""
    ensure_dirs()
    lock_path = LOCKS_DIR / f'{name}.lock'
    if not lock_path.exists():
        return False
    if is_lock_holder_valid(name):
        return False
    try:
        lock_path.unlink(missing_ok=True)
        print(f"[LOCK] Cleared stale lock: {name}", flush=True)
        return True
    except OSError as e:
        print(f"[LOCK] Could not clear {name}: {e}", flush=True)
        return False


def try_acquire_lock(name: str) -> bool:
    """Return True if lock acquired, False if another valid holder exists."""
    if IS_LOCAL_DEV:
        return True
    ensure_dirs()
    lock_path = LOCKS_DIR / f'{name}.lock'

    if lock_path.exists():
        info = _read_lock_file(lock_path)
        if is_lock_holder_valid(name, info):
            return False
        clear_stale_lock(name)

    payload = {
        'pid': os.getpid(),
        'script': name,
        'started_at': time.time(),
        'host': os.environ.get('HOSTNAME') or os.environ.get('RAILWAY_REPLICA_ID') or '',
    }
    lock_path.write_text(json.dumps(payload), encoding='utf-8')
    _active_locks.append(lock_path)
    return True


def release_lock(name: str):
    if IS_LOCAL_DEV:
        return
    lock_path = LOCKS_DIR / f'{name}.lock'
    try:
        if not lock_path.exists():
            return
        info = _read_lock_file(lock_path)
        if info and info.get('pid') == os.getpid():
            lock_path.unlink(missing_ok=True)
            return
        raw = lock_path.read_text(encoding='utf-8').strip()
        if raw == str(os.getpid()):
            lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def lock_status() -> Dict[str, Dict[str, Any]]:
    """Return dict of lock names -> {pid, alive, valid, cmdline}."""
    ensure_dirs()
    status: Dict[str, Dict[str, Any]] = {}
    for lock_path in LOCKS_DIR.glob('*.lock'):
        name = lock_path.stem
        info = _read_lock_file(lock_path)
        pid = info.get('pid') if info else None
        cmdline = _proc_cmdline(pid) if isinstance(pid, int) and _pid_alive(pid) else ''
        valid = is_lock_holder_valid(name, info) if info else False
        status[name] = {
            'pid': pid,
            'alive': _pid_alive(pid) if isinstance(pid, int) else False,
            'valid': valid,
            'cmdline': cmdline[:120] if cmdline else None,
            'started_at': info.get('started_at') if info else None,
        }
    return status


def _cleanup_locks():
    for lock_path in list(_active_locks):
        try:
            if not lock_path.exists():
                continue
            info = _read_lock_file(lock_path)
            if info and info.get('pid') == os.getpid():
                lock_path.unlink(missing_ok=True)
        except OSError:
            pass


atexit.register(_cleanup_locks)
