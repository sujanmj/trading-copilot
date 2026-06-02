#!/usr/bin/env python3
"""
Validate GET /api/debug/market-memory/dashboard via local API.

Usage:
  python scripts/validate_market_memory_dashboard_api.py

Prints exactly MARKET_MEMORY_DASHBOARD_API_OK on success; exits 1 on failure.
Graceful message when server is not running.
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
API_PATH = '/api/debug/market-memory/dashboard?limit=50'

REQUIRED_TOP_KEYS = ('ok', 'stats', 'learning', 'advisor', 'outcome_audit')


def _fail(msg: str) -> int:
    print(f'MARKET_MEMORY_DASHBOARD_API_FAIL: {msg}', file=sys.stderr)
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


def _fetch_dashboard(api_key: str = '', *, auth_retried: bool = False) -> tuple[dict | None, str | None]:
    url = API_BASE.rstrip('/') + API_PATH
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = resp.read().decode('utf-8')
            payload = json.loads(body)
            if not isinstance(payload, dict):
                return None, 'invalid JSON object'
            return payload, None
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) and not auth_retried:
            retry_key = api_key or _load_api_key()
            return _fetch_dashboard(api_key=retry_key, auth_retried=True)
        try:
            detail = exc.read().decode('utf-8', errors='replace')[:200]
        except Exception:
            detail = str(exc)
        return None, f'HTTP {exc.code}: {detail}'
    except urllib.error.URLError as exc:
        reason = getattr(exc, 'reason', exc)
        return None, f'server not reachable ({reason})'
    except json.JSONDecodeError as exc:
        return None, f'invalid JSON: {exc}'
    except Exception as exc:
        return None, str(exc)


def main() -> int:
    api_key = _load_api_key()
    payload, err = _fetch_dashboard(api_key=api_key)
    if payload is None:
        if err and 'server not reachable' in err.lower():
            print(
                'MARKET_MEMORY_DASHBOARD_API_SKIP: local API not running '
                f'at {API_BASE} — start with: python run_local.py',
                file=sys.stderr,
            )
            return 1
        return _fail(err or 'unknown fetch error')

    if payload.get('ok') is not True:
        return _fail(f"ok != true: {payload.get('error') or payload}")

    for key in REQUIRED_TOP_KEYS:
        if key not in payload:
            return _fail(f'missing key: {key}')

    if not isinstance(payload.get('stats'), dict):
        return _fail('stats is not an object')
    if not isinstance(payload.get('learning'), dict):
        return _fail('learning is not an object')
    if not isinstance(payload.get('advisor'), dict):
        return _fail('advisor is not an object')
    if not isinstance(payload.get('outcome_audit'), dict):
        return _fail('outcome_audit is not an object')

    print('MARKET_MEMORY_DASHBOARD_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
