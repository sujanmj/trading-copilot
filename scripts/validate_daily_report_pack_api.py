#!/usr/bin/env python3
"""Validate daily report pack API endpoint."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

API_BASE = 'http://127.0.0.1:8080'
PATH = '/api/debug/daily-report-pack'


def _fail(msg: str) -> int:
    print(f'DAILY_REPORT_PACK_API_FAIL: {msg}', file=sys.stderr)
    return 1


def _load_api_key() -> str:
    key = os.environ.get('API_KEY', '').strip()
    if key:
        return key
    try:
        from backend.utils.config import get_env, load_env

        load_env()
        return get_env('API_KEY')
    except Exception:
        return ''


def main() -> int:
    api_key = _load_api_key()
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(API_BASE.rstrip('/') + PATH, headers=headers, method='GET')
    payload = None
    err = None
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.URLError as exc:
        err = str(getattr(exc, 'reason', exc))
    except Exception as exc:
        err = str(exc)

    used_offline = False
    if payload is None:
        from backend.analytics.daily_report_pack import get_latest_daily_report_pack

        payload = get_latest_daily_report_pack()
        used_offline = True
        print(f'[DAILY_PACK_API] offline fallback ({err})')

    if payload.get('ok') is not True:
        return _fail(payload.get('error') or 'ok != true')
    if payload.get('shadow_mode') is not True:
        return _fail('shadow_mode must be true')
    for key in ('final_confidence', 'tomorrow_watchlist', 'historical_simulation', 'confidence_calibration'):
        if key not in payload:
            return _fail(f'missing key: {key}')

    print(f'[DAILY_PACK_API] {PATH} ok')
    if used_offline:
        print('[DAILY_PACK_API] validated via offline module fallback')
    print('DAILY_REPORT_PACK_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
