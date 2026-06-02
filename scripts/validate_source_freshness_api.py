#!/usr/bin/env python3
"""
Validate GET /api/debug/source-freshness via local API or direct handler.

Usage:
  python scripts/validate_source_freshness_api.py

Prints exactly SOURCE_FRESHNESS_API_OK on success; exits 1 on failure.
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
API_PATH = '/api/debug/source-freshness'

REQUIRED_KEYS = (
    'ok',
    'market_status',
    'runtime_snapshot_age_hours',
    'latest_market_data_age_hours',
    'enriched_price_age_hours',
    'news_age_hours',
    'sources',
    'warnings',
)


def _fail(msg: str) -> int:
    print(f'SOURCE_FRESHNESS_API_FAIL: {msg}', file=sys.stderr)
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


def _fetch_http(api_key: str = '', *, auth_retried: bool = False) -> tuple[dict | None, str | None]:
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
            return _fetch_http(api_key=retry_key, auth_retried=True)
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


def _validate_payload(payload: dict) -> str | None:
    if payload.get('ok') is not True:
        return f"ok != true: {payload.get('error') or payload}"
    for key in REQUIRED_KEYS:
        if key not in payload:
            return f'missing key: {key}'
    sources = payload.get('sources') or {}
    for section in ('prices', 'news', 'reddit', 'global', 'govt', 'market_memory'):
        if section not in sources:
            return f'missing sources.{section}'
    if not isinstance(payload.get('warnings'), list):
        return 'warnings must be a list'
    return None


def main() -> int:
    api_key = _load_api_key()
    payload, err = _fetch_http(api_key=api_key)

    if payload is None:
        try:
            from backend.analytics.source_freshness import get_source_freshness_report

            payload = get_source_freshness_report()
            err = None
        except Exception as exc:
            try:
                from backend.api.api_server import api_debug_source_freshness

                payload = api_debug_source_freshness()
                err = None
            except Exception as exc2:
                detail = err or str(exc2)
                return _fail(f'fetch failed ({detail}); direct report failed: {exc}')

    validation_err = _validate_payload(payload)
    if validation_err:
        return _fail(validation_err)

    print('SOURCE_FRESHNESS_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
