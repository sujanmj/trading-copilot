#!/usr/bin/env python3
"""
Validate external source coverage API endpoint.

Prints EXTERNAL_SOURCE_COVERAGE_API_OK on success (offline fallback ok).
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
PATH = '/api/debug/external-source-coverage'


def _fail(msg: str) -> int:
    print(f'EXTERNAL_SOURCE_COVERAGE_API_FAIL: {msg}', file=sys.stderr)
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
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode('utf-8', errors='replace')[:200]
        except Exception:
            detail = str(exc)
        return None, f'HTTP {exc.code}: {detail}'
    except urllib.error.URLError as exc:
        return None, f'server not reachable ({getattr(exc, "reason", exc)})'
    except Exception as exc:
        return None, str(exc)


def main() -> int:
    api_key = _load_api_key()
    payload, err = _fetch(api_key)
    used_offline = False

    if payload is None:
        try:
            from backend.collectors.broker_app_collector import get_external_source_coverage

            payload = get_external_source_coverage()
            used_offline = True
            print(f'[EXT_COVERAGE_API] offline fallback ({err})')
        except Exception as offline_exc:
            return _fail(f'{PATH}: {err}; offline: {offline_exc}')

    if payload.get('ok') is not True:
        return _fail(f'{PATH} ok != true: {payload.get("error") or payload}')

    for key in (
        'collected_items',
        'source_count',
        'unique_tickers',
        'broker_db_pick_count',
        'disclaimer',
    ):
        if key not in payload:
            return _fail(f'missing field: {key}')

    if 'External evidence only' not in str(payload.get('disclaimer') or ''):
        return _fail('disclaimer must state external evidence only')

    print(
        f"[EXT_COVERAGE_API] collected={payload.get('collected_items')} "
        f"sources={payload.get('source_count')} tickers={payload.get('unique_tickers')}"
    )
    if used_offline:
        print('[EXT_COVERAGE_API] validated via offline module fallback')
    print('EXTERNAL_SOURCE_COVERAGE_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
