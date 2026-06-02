#!/usr/bin/env python3
"""
Validate refresh-local-intelligence scopes (Stage 20B).

POST /api/debug/refresh-local-intelligence with dry_run=false for runtime, news, prices, memory.
Falls back to direct run_refresh_scoped when API is down.

Prints exactly REFRESH_SCOPES_OK on success.
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
API_PATH = '/api/debug/refresh-local-intelligence'
SCOPES = ('runtime', 'news', 'prices', 'memory')
REQUIRED_KEYS = ('ok', 'scope', 'dry_run', 'runtime', 'news', 'prices', 'memory', 'warnings')


def _fail(msg: str) -> int:
    print(f'REFRESH_SCOPES_FAIL: {msg}', file=sys.stderr)
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


def _post_scope(scope: str, api_key: str = '', *, auth_retried: bool = False) -> tuple[dict | None, str | None]:
    url = API_BASE.rstrip('/') + API_PATH
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    if api_key:
        headers['X-API-Key'] = api_key
    body = json.dumps({'scope': scope, 'dry_run': False}).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
            if not isinstance(payload, dict):
                return None, 'invalid JSON object'
            return payload, None
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) and not auth_retried:
            return _post_scope(scope, api_key=_load_api_key(), auth_retried=True)
        try:
            detail = exc.read().decode('utf-8', errors='replace')[:200]
        except Exception:
            detail = str(exc)
        return None, f'HTTP {exc.code}: {detail}'
    except urllib.error.URLError as exc:
        reason = getattr(exc, 'reason', exc)
        return None, f'server not reachable ({reason})'
    except Exception as exc:
        return None, str(exc)


def _direct(scope: str) -> dict:
    from scripts.refresh_local_intelligence import run_refresh_scoped

    return run_refresh_scoped(scope, dry_run=False)


def _validate(payload: dict, scope: str) -> str | None:
    for key in REQUIRED_KEYS:
        if key not in payload:
            return f'missing key: {key} (scope={scope})'
    if payload.get('scope') != scope:
        return f"scope mismatch: expected {scope!r}, got {payload.get('scope')!r}"
    if payload.get('dry_run') is not False:
        return f'dry_run must be false (scope={scope})'
    if not isinstance(payload.get('warnings'), list):
        return 'warnings must be a list'
    local_only = str(payload.get('error', '')).startswith('refresh-local-intelligence is local-only')
    if payload.get('ok') is not True and not local_only:
        return f"ok != true ({payload.get('error') or payload})"
    return None


def main() -> int:
    api_key = _load_api_key()
    for scope in SCOPES:
        payload, err = _post_scope(scope, api_key=api_key)
        if payload is None:
            try:
                payload = _direct(scope)
            except Exception as exc:
                return _fail(f'scope={scope}: fetch failed ({err}); direct: {exc}')

        validation_err = _validate(payload, scope)
        if validation_err:
            return _fail(validation_err)

        print(f'[REFRESH_SCOPES] {scope} ok dry_run={payload.get("dry_run")}')

    print('REFRESH_SCOPES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
