#!/usr/bin/env python3
"""
run_local.py — deterministic single-process local runtime.

Usage:
  python run_local.py
  set LOCAL_FORCE_EOD=1 && python run_local.py

Starts API + in-process scheduler + telegram + validation loop.
No Railway singleton locks or cloud recovery in LOCAL_DEV_MODE.
"""

from __future__ import annotations

import os
import sys

# Must set before any backend import (config reads LOCAL_DEV_MODE at import).
os.environ.setdefault('LOCAL_DEV_MODE', '1')
os.environ.setdefault('HOST', '127.0.0.1')
os.environ.setdefault('PORT', '8080')
os.environ.setdefault('API_BASE_URL', 'http://127.0.0.1:8080')
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
os.environ.setdefault('PYTHONUTF8', '1')
os.environ.setdefault('TZ', 'Asia/Kolkata')

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from backend.utils.bootstrap import setup_project_path

setup_project_path()

from backend.utils.local_runtime import free_port, local_log, prepare_local_env
from backend.utils.config import API_HOST, API_PORT, LOCAL_FORCE_EOD


def main() -> int:
    prepare_local_env()
    local_log('LOCAL RUNTIME', '=' * 50)
    local_log('LOCAL RUNTIME', 'Trading Copilot — LOCAL STABILIZATION MODE')
    local_log('LOCAL RUNTIME', f'LOCAL_FORCE_EOD={"1" if LOCAL_FORCE_EOD else "0"}')
    local_log('LOCAL RUNTIME', '=' * 50)

    free_port(int(os.environ.get('PORT', API_PORT)))

    try:
        import uvicorn
        from backend.api.api_server import app, local_auth_bypass_enabled
    except ImportError as e:
        local_log('AUTOFIX', f'Missing dependency: {e}')
        return 1

    host = os.environ.get('HOST', API_HOST)
    port = int(os.environ.get('PORT', API_PORT))
    local_log('LOCAL RUNTIME', f'uvicorn http://{host}:{port}')
    if local_auth_bypass_enabled():
        local_log('LOCAL AUTH', 'bypass active for localhost (no X-API-Key required)')
    local_log('LOCAL RUNTIME', 'After stable logs: npm start in frontend/')

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level='info',
        reload=False,
        workers=1,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
