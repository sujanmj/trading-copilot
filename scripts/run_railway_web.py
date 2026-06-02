#!/usr/bin/env python3
"""
Railway web/API service entrypoint (Stage 46F monolith).

Usage:
  python scripts/run_railway_web.py

Binds HOST=0.0.0.0 and PORT from env. Starts FastAPI + scheduler + AstraEdge Telegram
when TELEGRAM_COMMANDS_ENABLED=1 and DISABLE_TELEGRAM_LISTENER=0.
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
    'DISABLE_LEGACY_TELEGRAM_LISTENER': '1',
    'TELEGRAM_COMMANDS_ENABLED': '1',
    'DISABLE_TELEGRAM_LISTENER': '0',
    'DISABLE_TELEGRAM': '0',
    'DISABLE_TELEGRAM_SENDS': '0',
    'TELEGRAM_TRADE_COMMANDS_ENABLED': '0',
    'DISABLE_TRADE_EXECUTION': '1',
}
for _key, _val in _RAILWAY_WEB_DEFAULTS.items():
    os.environ.setdefault(_key, _val)

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
    from backend.config.local_safe_mode import is_legacy_telegram_listener_disabled, is_railway_mode
    from backend.storage.data_paths import get_data_root, log_data_startup
    from backend.telegram.response_format import TRADE_EXECUTION_PERMANENTLY_DISABLED

    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', '8080'))
    listener_disabled = os.environ.get('DISABLE_TELEGRAM_LISTENER', '').strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )
    legacy_disabled = is_legacy_telegram_listener_disabled()

    log_data_startup()

    from backend.analytics.railway_decision_bootstrap import start_background_report_bootstrap

    start_background_report_bootstrap()

    print('[RAILWAY_WEB] starting API service', flush=True)
    print(f'[RAILWAY_WEB] host={host} port={port}', flush=True)
    print(f'[RAILWAY_WEB] data_root={get_data_root()}', flush=True)
    print(f'[RAILWAY_WEB] telegram_listener_disabled={listener_disabled}', flush=True)
    print(f'[RAILWAY_WEB] legacy_telegram_listener_disabled={legacy_disabled}', flush=True)
    print(f'[RAILWAY_WEB] trade_execution_disabled={TRADE_EXECUTION_PERMANENTLY_DISABLED}', flush=True)

    if legacy_disabled and is_railway_mode():
        print('LEGACY_TELEGRAM_LISTENER_DISABLED', flush=True)

    from backend.telegram.telegram_analysis_bot import ensure_astraedge_telegram_started

    astraedge_started = ensure_astraedge_telegram_started()
    print(
        f'[RAILWAY_WEB] astraedge_telegram_started={astraedge_started} '
        f'legacy_telegram_started=False',
        flush=True,
    )

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
