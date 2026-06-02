#!/usr/bin/env python3
"""
Validate tomorrow watchlist API endpoint.

Prints exactly TOMORROW_WATCHLIST_API_OK on success (offline fallback allowed).
"""

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
PATH = '/api/debug/tomorrow-watchlist'


def _fail(msg: str) -> int:
    print(f'TOMORROW_WATCHLIST_API_FAIL: {msg}', file=sys.stderr)
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


def _fetch(api_key: str) -> tuple[dict | None, str | None]:
    url = API_BASE.rstrip('/') + PATH
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
            if not isinstance(payload, dict):
                return None, 'invalid JSON object'
            return payload, None
    except urllib.error.URLError as exc:
        return None, f'server not reachable ({getattr(exc, "reason", exc)})'
    except Exception as exc:
        return None, str(exc)


def _validate(payload: dict) -> str | None:
    if payload.get('ok') is not True:
        return payload.get('error') or 'ok != true'
    if payload.get('shadow_mode') is not True:
        return 'shadow_mode must be true'
    for key in ('summary', 'top_watchlist', 'avoid', 'no_decision', 'disclaimer'):
        if key not in payload:
            return f'missing key: {key}'
    return None


def main() -> int:
    api_key = _load_api_key()
    payload, err = _fetch(api_key)
    used_offline = False

    if payload is None:
        try:
            from backend.analytics.tomorrow_watchlist_report import get_top_watchlist_dashboard

            payload = get_top_watchlist_dashboard(limit=25)
            used_offline = True
            print(f'[TOMORROW_WATCHLIST_API] offline fallback ({err})')
        except Exception as offline_exc:
            return _fail(f'{PATH}: {err}; offline: {offline_exc}')

    validation_err = _validate(payload)
    if validation_err:
        return _fail(f'{PATH}: {validation_err}')

    print(f'[TOMORROW_WATCHLIST_API] {PATH} ok')
    if used_offline:
        print('[TOMORROW_WATCHLIST_API] validated via offline module fallback')
    print('TOMORROW_WATCHLIST_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
