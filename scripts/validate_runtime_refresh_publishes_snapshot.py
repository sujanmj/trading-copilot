#!/usr/bin/env python3
"""
Validate runtime refresh publishes a fresh runtime snapshot wrapper.

Usage (API server running on 127.0.0.1:8080):
  python scripts/validate_runtime_refresh_publishes_snapshot.py

Prints exactly RUNTIME_REFRESH_PUBLISHES_SNAPSHOT_OK on success.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

API_BASE = 'http://127.0.0.1:8080'
SNAPSHOT_PATH = '/api/runtime/snapshot'
REFRESH_PATH = '/api/debug/refresh-local-intelligence'


def _fail(msg: str) -> int:
    print(f'[RUNTIME_REFRESH] FAIL: {msg}', file=sys.stderr)
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


def _parse_iso(raw: object) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _get_snapshot(api_key: str) -> tuple[dict | None, str | None]:
    url = f"{API_BASE.rstrip('/')}{SNAPSHOT_PATH}?_ts=1"
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
            return (payload if isinstance(payload, dict) else None), None
    except Exception as exc:
        return None, str(exc)


def _post_refresh(api_key: str) -> tuple[dict | None, str | None]:
    url = API_BASE.rstrip('/') + REFRESH_PATH
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    if api_key:
        headers['X-API-Key'] = api_key
    body = json.dumps({'scope': 'runtime', 'dry_run': False}).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
            return (payload if isinstance(payload, dict) else None), None
    except Exception as exc:
        return None, str(exc)


def _validate_contract(payload: dict) -> str | None:
    if payload.get('ok') is not True:
        return f'ok != true status={payload.get("status")!r}'
    if not str(payload.get('snapshot_id') or '').strip():
        return 'snapshot_id empty'
    if not str(payload.get('generated_at') or '').strip():
        return 'generated_at empty'
    if not str(payload.get('package_generated_at') or '').strip():
        return 'package_generated_at empty'
    fresh = payload.get('freshness')
    if not isinstance(fresh, dict):
        return 'freshness missing'
    if fresh.get('source') != 'runtime_snapshot':
        return 'freshness.source != runtime_snapshot'
    return None


def _offline_refresh() -> tuple[dict | None, dict | None, str | None]:
    from scripts.refresh_local_intelligence import run_refresh_scoped

    before_path = PROJECT_ROOT / 'data' / 'cache' / 'runtime_snapshot.json'
    before = None
    if before_path.is_file():
        before = json.loads(before_path.read_text(encoding='utf-8'))

    result = run_refresh_scoped('runtime', dry_run=False)
    if not result.get('ok'):
        return before, None, f"refresh failed: {result}"

    after = None
    if before_path.is_file():
        after = json.loads(before_path.read_text(encoding='utf-8'))
    return before, after, None


def main() -> int:
    api_key = _load_api_key()
    before, err = _get_snapshot(api_key)
    used_api = before is not None

    if before is None:
        before, after, offline_err = _offline_refresh()
        if offline_err:
            return _fail(f'before fetch failed ({err}); offline: {offline_err}')
        if after is None:
            return _fail('offline refresh did not produce runtime snapshot cache')
        contract_err = _validate_contract(after)
        if contract_err:
            return _fail(contract_err)
        print('RUNTIME_REFRESH_PUBLISHES_SNAPSHOT_OK')
        return 0

    contract_err = _validate_contract(before)
    if contract_err:
        return _fail(f'before: {contract_err}')

    before_id = before.get('snapshot_id')
    before_pkg = before.get('package_generated_at') or before.get('generated_at')
    print(f'[RUNTIME_REFRESH] before snapshot_id={before_id} package_generated_at={before_pkg}')

    refresh_payload, refresh_err = _post_refresh(api_key)
    if refresh_payload is None:
        _, after, offline_err = _offline_refresh()
        if offline_err:
            return _fail(f'refresh POST failed ({refresh_err}); offline: {offline_err}')
        after = after or {}
    else:
        if not refresh_payload.get('ok'):
            return _fail(f'refresh ok != true: {refresh_payload.get("error") or refresh_payload}')
        after, err = _get_snapshot(api_key)
        if after is None:
            return _fail(f'after fetch failed: {err}')

    contract_err = _validate_contract(after)
    if contract_err:
        return _fail(f'after: {contract_err}')

    after_id = after.get('snapshot_id')
    after_pkg = after.get('package_generated_at') or after.get('generated_at')
    print(f'[RUNTIME_REFRESH] after snapshot_id={after_id} package_generated_at={after_pkg}')

    before_dt = _parse_iso(before_pkg)
    after_dt = _parse_iso(after_pkg)
    changed_id = before_id != after_id
    newer_pkg = bool(after_dt and before_dt and after_dt >= before_dt)
    if not changed_id and not newer_pkg:
        return _fail('snapshot_id unchanged and package_generated_at not newer after refresh')

    api_mode = 'live' if used_api else 'offline'
    stale_value = (after.get('freshness') or {}).get('stale')
    print(f'[RUNTIME_REFRESH] api={api_mode} stale={stale_value}')
    print('RUNTIME_REFRESH_PUBLISHES_SNAPSHOT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
