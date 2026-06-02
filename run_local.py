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
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Must set before any backend import (config reads LOCAL_* at import).
_LOCAL_DEFAULTS = {
    'LOCAL_DEV_MODE': '1',
    'LOCAL_ONLY': '1',
    'HOST': '127.0.0.1',
    'PORT': '8080',
    'API_BASE_URL': 'http://127.0.0.1:8080',
    'DISABLE_RAILWAY_API': '1',
    'PYTHONIOENCODING': 'utf-8',
    'PYTHONUTF8': '1',
    'TZ': 'Asia/Kolkata',
    'LOCAL_QUIET_MODE': '1',
}
for _key, _val in _LOCAL_DEFAULTS.items():
    os.environ.setdefault(_key, _val)

from backend.config.local_safe_mode import apply_local_safe_mode_defaults

apply_local_safe_mode_defaults()

print('[LOCAL MODE] LOCAL_DEV_MODE=1 LOCAL_ONLY=1', flush=True)
print('[LOCAL MODE] API http://127.0.0.1:8080 — Telegram disabled', flush=True)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from backend.utils.bootstrap import setup_project_path

setup_project_path()

from backend.utils.local_runtime import free_port, local_log, prepare_local_env
from backend.utils.config import (
    API_HOST,
    API_PORT,
    DISABLE_TELEGRAM,
    DISABLE_TELEGRAM_LISTENER,
    DISABLE_TELEGRAM_SENDS,
    LOCAL_FORCE_EOD,
    LOCAL_ONLY,
)


def main() -> int:
    prepare_local_env()
    local_log('LOCAL RUNTIME', '=' * 50)
    local_log('LOCAL RUNTIME', 'Trading Copilot — LOCAL LAPTOP MODE')
    local_log('LOCAL RUNTIME', f'LOCAL_ONLY={"1" if LOCAL_ONLY else "0"}')
    local_log('LOCAL RUNTIME', f'LOCAL_FORCE_EOD={"1" if LOCAL_FORCE_EOD else "0"}')
    local_log('LOCAL RUNTIME', f'TELEGRAM disabled listener={DISABLE_TELEGRAM_LISTENER} sends={DISABLE_TELEGRAM_SENDS} all={DISABLE_TELEGRAM}')
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
