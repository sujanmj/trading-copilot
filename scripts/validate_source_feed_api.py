#!/usr/bin/env python3
"""
Validate GET /api/debug/source-feed via local API or module fallback (Stage 44Q).

Prints exactly SOURCE_FEED_API_OK on success.
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
API_PATH = '/api/debug/source-feed'

REQUIRED_KEYS = (
    'ok',
    'source',
    'source_label',
    'items',
    'counts',
    'last_updated',
)


def _fail(msg: str) -> int:
    print(f'SOURCE_FEED_API_FAIL: {msg}', file=sys.stderr)
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


def _fetch_http(source: str, api_key: str = '', *, auth_retried: bool = False) -> tuple[dict | None, str | None]:
    from urllib.parse import quote

    url = f"{API_BASE.rstrip('/')}{API_PATH}?source={quote(source)}&limit=20"
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
            return _fetch_http(source, api_key=retry_key, auth_retried=True)
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


def _validate_payload(payload: dict, expected_source: str) -> str | None:
    if payload.get('ok') is not True:
        return f"ok != true for {expected_source}: {payload.get('error')}"
    for key in REQUIRED_KEYS:
        if key not in payload:
            return f'missing key: {key}'
    if payload.get('source') != expected_source:
        return f"source mismatch: {payload.get('source')}"
    counts = payload.get('counts')
    if not isinstance(counts, dict):
        return 'counts must be object'
    for ck in ('total', 'stock_news', 'market_context', 'macro_context', 'broker_candidates'):
        if ck not in counts:
            return f'counts missing {ck}'
    items = payload.get('items')
    if not isinstance(items, list):
        return 'items must be list'
    return None


def _module_feed(source: str) -> dict:
    from backend.analytics.source_feed_viewer import get_source_feed

    return get_source_feed(source, limit=20)


def _resolve_payload(source: str, api_key: str) -> tuple[dict | None, str | None]:
    payload, err = _fetch_http(source, api_key=api_key)
    if payload is not None:
        return payload, None
    try:
        return _module_feed(source), None
    except Exception as exc:
        return None, err or str(exc)


def main() -> int:
    api_key = _load_api_key()
    payload, err = _resolve_payload('ET', api_key)
    if payload is None:
        return _fail(f'ET fetch failed: {err}')

    validation_err = _validate_payload(payload, 'ET')
    if validation_err:
        return _fail(validation_err)

    if not (payload.get('items') or []):
        return _fail('ET must return cached items when Economic Times data exists')

    ndtv_payload, ndtv_err = _resolve_payload('NDTV', api_key)
    if ndtv_payload is None:
        return _fail(f'NDTV fetch failed: {ndtv_err}')
    ndtv_validation = _validate_payload(ndtv_payload, 'NDTV')
    if ndtv_validation:
        return _fail(ndtv_validation)
    if not (ndtv_payload.get('items') or []):
        return _fail('NDTV must return cached items when NDTV Profit data exists')

    print('SOURCE_FEED_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
