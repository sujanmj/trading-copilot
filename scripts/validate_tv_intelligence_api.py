#!/usr/bin/env python3
"""
Validate TV intelligence API endpoints.

Usage (API server running on 127.0.0.1:8080):
  python scripts/validate_tv_intelligence_api.py

Prints exactly TV_INTELLIGENCE_API_OK on success.
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
PATHS = ('/api/debug/tv-intelligence', '/api/youtube')
REQUIRED_KEYS = ('ok', 'generated_at', 'source', 'videos', 'summary', 'warnings')


def _fail(msg: str) -> int:
    print(f'TV_INTELLIGENCE_API_FAIL: {msg}', file=sys.stderr)
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
        reason = getattr(exc, 'reason', exc)
        return None, f'server not reachable ({reason})'
    except Exception as exc:
        return None, str(exc)


def _validate_payload(payload: dict, path: str) -> str | None:
    for key in REQUIRED_KEYS:
        if key not in payload:
            return f'{path} missing key: {key}'
    if not isinstance(payload.get('videos'), list):
        return f'{path} videos must be list'
    summary = payload.get('summary')
    if not isinstance(summary, dict):
        return f'{path} summary must be object'
    for key in ('total', 'live_count', 'recent_count'):
        if key not in summary:
            return f'{path} summary missing {key}'
    return None


def main() -> int:
    api_key = _load_api_key()
    for path in PATHS:
        payload, err = _fetch(path, api_key)
        if payload is None:
            try:
                from backend.collectors.tv_intelligence_collector import load_cached_tv_intelligence

                payload = load_cached_tv_intelligence()
                print(f'[TV_INTEL_API] offline fallback for {path} ({err})')
            except Exception as offline_exc:
                return _fail(f'{path}: {err}; offline: {offline_exc}')

        validation_err = _validate_payload(payload, path)
        if validation_err:
            return _fail(validation_err)
        print(f"[TV_INTEL_API] {path} ok videos={payload.get('summary', {}).get('total', len(payload.get('videos') or []))}")

    print('TV_INTELLIGENCE_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
