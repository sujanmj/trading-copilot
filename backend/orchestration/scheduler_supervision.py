"""Small process-wait helper for bounded scheduler recovery."""
from __future__ import annotations

import subprocess
import time
from typing import Callable


def wait_for_child(
    process,
    *,
    scheduler: bool,
    recovery_requested: Callable[[], bool],
    scheduler_healthy: Callable[[], bool],
    poll_seconds: int = 15,
    terminate_timeout: int = 15,
    startup_grace_seconds: int = 60,
) -> int:
    """Wait for exit; restart an unhealthy scheduler on signal after startup grace."""
    if not scheduler:
        process.wait()
        return process.returncode if process.returncode is not None else -1

    started_at = time.monotonic()
    while True:
        try:
            process.wait(timeout=poll_seconds)
            return process.returncode if process.returncode is not None else -1
        except subprocess.TimeoutExpired:
            if time.monotonic() - started_at < startup_grace_seconds:
                continue
            if not recovery_requested() or scheduler_healthy():
                continue

            print('[ORCHESTRATOR] unhealthy scheduler recovery — stopping child for relaunch', flush=True)
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.wait(timeout=terminate_timeout)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    pass
                process.wait(timeout=terminate_timeout)
            return process.returncode if process.returncode is not None else -1
