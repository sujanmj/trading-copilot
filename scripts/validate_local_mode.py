#!/usr/bin/env python3
"""
Validate LOCAL LAPTOP MODE configuration.

Usage:
  python scripts/validate_local_mode.py

Prints LOCAL_MODE_OK on success; exits 1 on failure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
RAILWAY_FALLBACK = 'web-production-0592e.up.railway.app'

_REQUIRED_DEFAULTS = {
    'LOCAL_DEV_MODE': '1',
    'LOCAL_ONLY': '1',
    'HOST': '127.0.0.1',
    'PORT': '8080',
    'API_BASE_URL': 'http://127.0.0.1:8080',
    'DISABLE_TELEGRAM': '1',
    'DISABLE_TELEGRAM_LISTENER': '1',
    'DISABLE_TELEGRAM_SENDS': '1',
    'DISABLE_RAILWAY_API': '1',
}


def _fail(msg: str) -> int:
    print(f'LOCAL_MODE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for key, val in _REQUIRED_DEFAULTS.items():
        os.environ.setdefault(key, val)

    if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
        os.chdir(PROJECT_ROOT)

    sys.path.insert(0, str(PROJECT_ROOT))

    from backend.utils import config as cfg
    from backend.utils import telegram_guard as tg

    checks: list[str] = []

    if not cfg.IS_LOCAL_DEV:
        return _fail('IS_LOCAL_DEV is False')
    checks.append('IS_LOCAL_DEV')

    if not cfg.LOCAL_ONLY:
        return _fail('LOCAL_ONLY is False')
    checks.append('LOCAL_ONLY')

    if not (cfg.DISABLE_TELEGRAM and cfg.DISABLE_TELEGRAM_LISTENER and cfg.DISABLE_TELEGRAM_SENDS):
        return _fail('Telegram disable flags not all True')
    checks.append('telegram_disabled')

    if cfg.API_HOST != '127.0.0.1':
        return _fail(f'API_HOST={cfg.API_HOST!r} expected 127.0.0.1')
    checks.append('API_HOST')

    if cfg.API_PORT != 8080:
        return _fail(f'API_PORT={cfg.API_PORT} expected 8080')
    checks.append('API_PORT')

    api_base = (cfg.API_BASE_URL or os.environ.get('API_BASE_URL', '')).rstrip('/')
    if api_base != 'http://127.0.0.1:8080':
        return _fail(f'API_BASE_URL={api_base!r} expected http://127.0.0.1:8080')
    checks.append('API_BASE_URL')

    if tg.is_telegram_send_enabled() or tg.is_telegram_listener_enabled():
        return _fail('telegram_guard reports Telegram still enabled')
    checks.append('telegram_guard')

    if not FRONTEND_INDEX.exists():
        return _fail(f'missing {FRONTEND_INDEX}')
    index_src = FRONTEND_INDEX.read_text(encoding='utf-8')
    if RAILWAY_FALLBACK in index_src:
        return _fail('frontend/index.html still contains Railway hardcoded fallback')
    if 'REMOTE_API_BASE' in index_src:
        return _fail('frontend/index.html still defines REMOTE_API_BASE')
    if "resolveApiBase()" not in index_src:
        return _fail('frontend/index.html missing resolveApiBase() local resolver')
    checks.append('frontend_api')

    run_local_src = (PROJECT_ROOT / 'run_local.py').read_text(encoding='utf-8')
    if 'LOCAL_ONLY' not in run_local_src or 'DISABLE_TELEGRAM' not in run_local_src:
        return _fail('run_local.py missing LOCAL_ONLY / DISABLE_TELEGRAM setdefaults')
    checks.append('run_local')

    if cfg.IS_RAILWAY:
        return _fail('IS_RAILWAY unexpectedly True in local validation env')
    checks.append('railway_unchanged')

    print('LOCAL_MODE_OK')
    print('checks:', ', '.join(checks))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
