#!/usr/bin/env python3
"""
Railway web/API service entrypoint (Stage 46A).

Usage:
  python scripts/run_railway_web.py

Binds HOST=0.0.0.0 and PORT from env. Starts FastAPI only.
Telegram listener is disabled unless ENABLE_TELEGRAM_IN_WEB=1.
"""

from __future__ import annotations

import os
import sys

_RAILWAY_WEB_DEFAULTS = {
    'LOCAL_DEV_MODE': '0',
    'LOCAL_ONLY': '0',
    'APP_MODE': 'railway',
    'HOST': '0.0.0.0',
    'TZ': 'Asia/Kolkata',
    'PYTHONIOENCODING': 'utf-8',
    'PYTHONUTF8': '1',
}
for _key, _val in _RAILWAY_WEB_DEFAULTS.items():
    os.environ.setdefault(_key, _val)

if not os.environ.get('ENABLE_TELEGRAM_IN_WEB', '').strip().lower() in ('1', 'true', 'yes', 'on'):
    os.environ.setdefault('DISABLE_TELEGRAM_LISTENER', '1')

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

from backend.utils.bootstrap import setup_project_path

setup_project_path()


def main() -> int:
    import uvicorn
    from backend.api.api_server import app
    from backend.storage.data_paths import get_data_root
    from backend.telegram.response_format import TRADE_EXECUTION_PERMANENTLY_DISABLED

    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', '8080'))
    listener_disabled = os.environ.get('DISABLE_TELEGRAM_LISTENER', '').strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )

    print('[RAILWAY_WEB] starting API service', flush=True)
    print(f'[RAILWAY_WEB] host={host} port={port}', flush=True)
    print(f'[RAILWAY_WEB] data_root={get_data_root()}', flush=True)
    print(f'[RAILWAY_WEB] telegram_listener_disabled={listener_disabled}', flush=True)
    print(f'[RAILWAY_WEB] trade_execution_disabled={TRADE_EXECUTION_PERMANENTLY_DISABLED}', flush=True)

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
