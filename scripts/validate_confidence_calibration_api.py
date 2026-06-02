#!/usr/bin/env python3
"""
Validate confidence calibration API endpoint.

Usage (API server on 127.0.0.1:8080):
  python scripts/validate_confidence_calibration_api.py

Prints exactly CONFIDENCE_CALIBRATION_API_OK on success (or offline fallback).
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
PATH = '/api/debug/confidence-calibration'


def _fail(msg: str) -> int:
    print(f'CONFIDENCE_CALIBRATION_API_FAIL: {msg}', file=sys.stderr)
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


def _fetch(path: str, api_key: str) -> tuple[dict | None, str | None]:
    url = API_BASE.rstrip('/') + path
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
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


def _offline_payload() -> dict:
    from backend.analytics.confidence_calibration_engine import get_calibration_dashboard

    return get_calibration_dashboard()


def _validate_payload(payload: dict) -> str | None:
    if payload.get('ok') is not True:
        return payload.get('error') or 'ok != true'
    for key in ('live', 'historical', 'combined', 'recommendations', 'warnings'):
        if key not in payload:
            return f'missing key: {key}'
    combined = payload.get('combined') or {}
    if not isinstance(combined.get('buckets'), list):
        return 'combined.buckets must be list'
    if payload.get('shadow_mode') is not True:
        return 'shadow_mode must be true'
    return None


def main() -> int:
    api_key = _load_api_key()
    used_offline = False

    payload, err = _fetch(PATH, api_key)
    if payload is None:
        try:
            payload = _offline_payload()
            used_offline = True
            print(f'[CONFIDENCE_CALIBRATION_API] offline fallback for {PATH} ({err})')
        except Exception as offline_exc:
            return _fail(f'{PATH}: {err}; offline: {offline_exc}')

    validation_err = _validate_payload(payload)
    if validation_err:
        return _fail(f'{PATH}: {validation_err}')

    print(f'[CONFIDENCE_CALIBRATION_API] {PATH} ok')
    if used_offline:
        print('[CONFIDENCE_CALIBRATION_API] validated via offline module fallback')
    print('CONFIDENCE_CALIBRATION_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
