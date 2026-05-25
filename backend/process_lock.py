"""
Cross-platform process locks — prevent duplicate schedulers / analyzers.
"""

import os
import sys
import atexit
from pathlib import Path

from config import LOCKS_DIR, ensure_dirs

_active_locks = []


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


def try_acquire_lock(name: str) -> bool:
    """Return True if lock acquired, False if another live process holds it."""
    ensure_dirs()
    lock_path = LOCKS_DIR / f'{name}.lock'

    if lock_path.exists():
        try:
            old_pid = int(lock_path.read_text(encoding='utf-8').strip())
            if _pid_alive(old_pid):
                return False
        except (ValueError, OSError):
            pass

    lock_path.write_text(str(os.getpid()), encoding='utf-8')
    _active_locks.append(lock_path)
    return True


def release_lock(name: str):
    lock_path = LOCKS_DIR / f'{name}.lock'
    try:
        if lock_path.exists():
            current = lock_path.read_text(encoding='utf-8').strip()
            if current == str(os.getpid()):
                lock_path.unlink()
    except OSError:
        pass


def lock_status():
    """Return dict of lock names -> {pid, alive}."""
    ensure_dirs()
    status = {}
    for lock_path in LOCKS_DIR.glob('*.lock'):
        name = lock_path.stem
        try:
            pid = int(lock_path.read_text(encoding='utf-8').strip())
            status[name] = {'pid': pid, 'alive': _pid_alive(pid)}
        except (ValueError, OSError):
            status[name] = {'pid': None, 'alive': False}
    return status


def _cleanup_locks():
    for lock_path in list(_active_locks):
        try:
            if lock_path.exists():
                current = lock_path.read_text(encoding='utf-8').strip()
                if current == str(os.getpid()):
                    lock_path.unlink()
        except OSError:
            pass


atexit.register(_cleanup_locks)
