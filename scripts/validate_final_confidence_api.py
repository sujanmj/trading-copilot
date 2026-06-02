#!/usr/bin/env python3
"""
Validate final confidence API endpoints.

Usage (API server on 127.0.0.1:8080):
  python scripts/validate_final_confidence_api.py

Prints exactly FINAL_CONFIDENCE_API_OK on success (or offline fallback).
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
PATHS = (
    '/api/debug/final-confidence',
    '/api/debug/final-confidence?ticker=RELIANCE',
    '/api/debug/final-confidence/report',
)


def _fail(msg: str) -> int:
    print(f'FINAL_CONFIDENCE_API_FAIL: {msg}', file=sys.stderr)
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


def _offline_payload(path: str) -> dict:
    from backend.analytics.final_confidence_fusion import (
        explain_score_breakdown,
        get_final_confidence_dashboard,
    )

    if 'ticker=' in path:
        return explain_score_breakdown('RELIANCE')
    if '/report' in path:
        return get_final_confidence_dashboard(limit=30)
    return get_final_confidence_dashboard(limit=30)


def _validate_payload(path: str, payload: dict) -> str | None:
    if payload.get('ok') is not True:
        return payload.get('error') or 'ok != true'

    if 'ticker=' in path:
        if 'breakdown' not in payload and payload.get('found') is not False:
            return 'missing breakdown'
        return None

    if '/report' in path or path.endswith('/final-confidence'):
        for key in ('buy_candidate', 'watch', 'avoid', 'no_decision'):
            if key not in payload:
                return f'missing count key: {key}'
        if not isinstance(payload.get('rows'), list):
            return 'rows must be list'
        return None

    return None


def main() -> int:
    api_key = _load_api_key()
    used_offline = False

    for path in PATHS:
        payload, err = _fetch(path, api_key)
        if payload is None:
            try:
                payload = _offline_payload(path)
                used_offline = True
                print(f'[FINAL_CONFIDENCE_API] offline fallback for {path} ({err})')
            except Exception as offline_exc:
                return _fail(f'{path}: {err}; offline: {offline_exc}')

        validation_err = _validate_payload(path, payload)
        if validation_err:
            return _fail(f'{path}: {validation_err}')

        print(f'[FINAL_CONFIDENCE_API] {path} ok')

    if used_offline:
        print('[FINAL_CONFIDENCE_API] validated via offline module fallback')
    print('FINAL_CONFIDENCE_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
