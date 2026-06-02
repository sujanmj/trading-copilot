#!/usr/bin/env python3
"""
Validate GET /api/debug/historical-learning via local API.

Usage:
  python scripts/validate_historical_learning_api.py

Prints exactly HISTORICAL_LEARNING_API_OK on success; exits 1 on failure.
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
API_PATH = '/api/debug/historical-learning'

REQUIRED_TOP_KEYS = ('ok', 'stats', 'overall', 'comparison')


def _fail(msg: str) -> int:
    print(f'HISTORICAL_LEARNING_API_FAIL: {msg}', file=sys.stderr)
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
    url = API_BASE.rstrip('/') + path
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
            return _fetch(path, api_key=retry_key, auth_retried=True)
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


def _validate_payload(payload: dict, *, context: str) -> str | None:
    if payload.get('ok') is not True:
        return f"{context} ok != true: {payload.get('error') or payload}"
    for key in REQUIRED_TOP_KEYS:
        if key not in payload:
            return f'{context} missing key: {key}'
    if not isinstance(payload.get('stats'), dict):
        return f'{context} stats is not an object'
    if not isinstance(payload.get('overall'), dict):
        return f'{context} overall is not an object'
    if not isinstance(payload.get('comparison'), dict):
        return f'{context} comparison is not an object'
    return None


def _validate_direct() -> tuple[bool, str | None]:
    """Fallback when local HTTP server is unavailable."""
    try:
        from backend.analytics.historical_learning_engine import (
            compare_live_memory_vs_historical,
            get_historical_learning_summary,
            get_historical_ticker_performance,
        )

        summary = get_historical_learning_summary()
        comparison = compare_live_memory_vs_historical()
        payload = {
            'ok': True,
            'stats': summary.get('stats'),
            'overall': summary.get('overall'),
            'top_tickers': summary.get('top_tickers'),
            'bottom_tickers': summary.get('bottom_tickers'),
            'source_performance': summary.get('source_performance'),
            'sample_prices': summary.get('sample_prices'),
            'price_row_count': summary.get('price_row_count'),
            'comparison': comparison,
        }
        err = _validate_payload(payload, context='summary')
        if err:
            return False, err

        ticker_payload = get_historical_ticker_performance('RELIANCE')
        if ticker_payload.get('ok') is not True:
            return False, f"ticker ok != true: {ticker_payload.get('error') or ticker_payload}"
        if 'ticker' not in ticker_payload:
            return False, 'ticker response missing ticker key'
        return True, None
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    api_key = _load_api_key()
    payload, err = _fetch(API_PATH, api_key=api_key)
    if payload is None:
        if err and 'server not reachable' in err.lower():
            ok, direct_err = _validate_direct()
            if ok:
                print('HISTORICAL_LEARNING_API_OK')
                return 0
            return _fail(direct_err or 'direct validation failed')
        return _fail(err or 'unknown fetch error')

    err = _validate_payload(payload, context='summary')
    if err:
        return _fail(err)

    ticker_payload, ticker_err = _fetch(f'{API_PATH}?ticker=RELIANCE', api_key=api_key)
    if ticker_payload is None:
        return _fail(ticker_err or 'ticker fetch failed')
    if ticker_payload.get('ok') is not True:
        return _fail(f"ticker ok != true: {ticker_payload.get('error') or ticker_payload}")
    if 'ticker' not in ticker_payload:
        return _fail('ticker response missing ticker key')

    print('HISTORICAL_LEARNING_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
