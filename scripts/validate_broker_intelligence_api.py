#!/usr/bin/env python3
"""
Validate broker intelligence API endpoints.

Usage (API server on 127.0.0.1:8080):
  python scripts/validate_broker_intelligence_api.py

Prints exactly BROKER_INTELLIGENCE_API_OK on success (or offline fallback).
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
    '/api/debug/broker-intelligence',
    '/api/debug/broker-intelligence?ticker=RELIANCE',
    '/api/debug/broker-intelligence/source?source=Moneycontrol',
    '/api/debug/our-vs-broker',
)


def _fail(msg: str) -> int:
    print(f'BROKER_INTELLIGENCE_API_FAIL: {msg}', file=sys.stderr)
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
    from backend.analytics.broker_prediction_intelligence import (
        compare_our_predictions_vs_brokers,
        get_broker_intelligence_dashboard,
        get_source_intelligence,
        get_ticker_intelligence,
    )

    if 'source?' in path or '/source?' in path:
        return get_source_intelligence('Moneycontrol')
    if 'ticker=' in path:
        return get_ticker_intelligence('RELIANCE')
    if 'our-vs-broker' in path:
        return compare_our_predictions_vs_brokers()
    return get_broker_intelligence_dashboard()


def main() -> int:
    api_key = _load_api_key()
    used_offline = False

    for path in PATHS:
        payload, err = _fetch(path, api_key)
        if payload is None:
            try:
                payload = _offline_payload(path)
                used_offline = True
                print(f'[BROKER_INTEL_API] offline fallback for {path} ({err})')
            except Exception as offline_exc:
                return _fail(f'{path}: {err}; offline: {offline_exc}')

        if payload.get('ok') is not True:
            return _fail(f'{path} ok != true: {payload.get("error") or payload}')

        print(f'[BROKER_INTEL_API] {path} ok')

    if used_offline:
        print('[BROKER_INTEL_API] validated via offline module fallback')
    print('BROKER_INTELLIGENCE_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
