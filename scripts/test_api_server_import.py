#!/usr/bin/env python3
"""Unit tests — backend.api.api_server import without NameError (Stage 50A emergency)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_LISTENER', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')
os.environ.setdefault('DISABLE_TRADE_EXECUTION', '1')


def _fail(msg: str) -> int:
    print(f'API_SERVER_IMPORT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    reg_idx = src.find('register_myfeed_routes(app')
    san_idx = src.find('def sanitize_json_value')
    if reg_idx < 0:
        return _fail('register_myfeed_routes call missing')
    if san_idx < 0:
        return _fail('sanitize_json_value definition missing')
    if reg_idx < san_idx:
        return _fail('register_myfeed_routes must run after sanitize_json_value is defined')

    try:
        from backend.api import api_server
    except NameError as exc:
        return _fail(f'NameError importing api_server: {exc}')
    except Exception as exc:
        return _fail(f'import api_server failed: {type(exc).__name__}: {exc}')

    if not hasattr(api_server, 'app'):
        return _fail('api_server.app missing')
    if not hasattr(api_server, 'sanitize_json_value'):
        return _fail('api_server.sanitize_json_value missing')

    route_paths = {getattr(r, 'path', None) for r in api_server.app.routes}
    if '/api/myfeed' not in route_paths:
        return _fail('/api/myfeed route not registered on app')

    print('API_SERVER_IMPORT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
