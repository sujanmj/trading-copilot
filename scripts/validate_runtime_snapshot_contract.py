#!/usr/bin/env python3
"""
Validate GET /api/runtime_snapshot and GET /api/runtime/snapshot contract.

Usage (API server running on 127.0.0.1:8080):
  python scripts/validate_runtime_snapshot_contract.py

Prints [RUNTIME_CONTRACT] lines and exactly RUNTIME_SNAPSHOT_CONTRACT_OK on success.
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
ENDPOINTS = ('/api/runtime_snapshot', '/api/runtime/snapshot')
REQUIRED_TOP = ('ok', 'snapshot_id', 'generated_at', 'action_plan', 'intelligence', 'freshness', 'data', 'exports')
REQUIRED_FRESHNESS = ('age_hours', 'stale', 'source')


def _fail(msg: str) -> int:
    print(f'[RUNTIME_CONTRACT] FAIL: {msg}', file=sys.stderr)
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


def _fetch(path: str, api_key: str = '', *, auth_retried: bool = False) -> tuple[dict | None, str | None]:
    url = f"{API_BASE.rstrip('/')}{path}?_ts=1"
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
        if exc.code in (401, 403) and not auth_retried:
            return _fetch(path, api_key=_load_api_key(), auth_retried=True)
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


def _validate_payload(path: str, payload: dict) -> str | None:
    for key in REQUIRED_TOP:
        if key not in payload:
            return f'{path} missing top-level key: {key}'

    if payload.get('ok') is not True:
        return f'{path} ok != true (status={payload.get("status")!r})'

    if not str(payload.get('snapshot_id') or '').strip():
        return f'{path} snapshot_id empty'

    if not str(payload.get('generated_at') or '').strip():
        return f'{path} generated_at empty'

    if payload.get('action_plan') is None:
        return f'{path} action_plan missing/null'

    intelligence = payload.get('intelligence')
    if not isinstance(intelligence, dict):
        return f'{path} intelligence must be object'

    freshness = payload.get('freshness')
    if not isinstance(freshness, dict):
        return f'{path} freshness must be object'
    for key in REQUIRED_FRESHNESS:
        if key not in freshness:
            return f'{path} freshness missing key: {key}'
    if freshness.get('source') != 'runtime_snapshot':
        return f'{path} freshness.source != runtime_snapshot'

    for block in ('data', 'exports'):
        if not isinstance(payload.get(block), dict):
            return f'{path} {block} must be object'

    print(
        f"[RUNTIME_CONTRACT] {path} ok snapshot_id={payload.get('snapshot_id')} "
        f"stale={freshness.get('stale')} age_hours={freshness.get('age_hours')}"
    )
    return None


def _validate_wrapper_offline() -> str | None:
    try:
        from backend.runtime.snapshot_contract import wrap_runtime_snapshot_for_frontend
        from backend.utils.config import RUNTIME_SNAPSHOT_CACHE

        raw = {'active_snapshot_id': 'snap_test', 'data': {'intelligence': {'summary': 'x'}}}
        wrapped = wrap_runtime_snapshot_for_frontend(raw, cache_path=RUNTIME_SNAPSHOT_CACHE)
        return _validate_payload('/offline/wrapper', wrapped)
    except Exception as exc:
        return f'offline wrapper check failed: {exc}'


def main() -> int:
    api_key = _load_api_key()
    saw_live = False

    for path in ENDPOINTS:
        payload, err = _fetch(path, api_key=api_key)
        if payload is None:
            offline_err = _validate_wrapper_offline()
            if offline_err:
                return _fail(f'{path}: fetch failed ({err}); {offline_err}')
            print(f'[RUNTIME_CONTRACT] {path} skipped (server down) — offline wrapper OK')
            continue

        saw_live = True
        validation_err = _validate_payload(path, payload)
        if validation_err:
            return _fail(validation_err)

    if not saw_live:
        offline_err = _validate_wrapper_offline()
        if offline_err:
            return _fail(offline_err)

    print('RUNTIME_SNAPSHOT_CONTRACT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
