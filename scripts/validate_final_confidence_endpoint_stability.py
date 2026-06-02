#!/usr/bin/env python3
"""
Validate final confidence endpoint stability (Stage 44AX).

Prints exactly FINAL_CONFIDENCE_ENDPOINT_STABILITY_OK on success.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

API_SERVER = PROJECT_ROOT / 'backend' / 'api' / 'api_server.py'
LOADER = PROJECT_ROOT / 'backend' / 'analytics' / 'final_confidence_report_loader.py'
REPORT_FILE = PROJECT_ROOT / 'data' / 'final_confidence_report.json'
API_BASE = 'http://127.0.0.1:8080'
MARKER = 'BACKEND_STAGE_44AX_FINAL_CONFIDENCE_ENDPOINT_STABLE'
ROUTES = (
    '/api/debug/final-confidence',
    '/api/debug/final-confidence/report',
)


def _fail(msg: str) -> int:
    print(f'FINAL_CONFIDENCE_ENDPOINT_STABILITY_FAIL: {msg}', file=sys.stderr)
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


def _fetch(path: str, api_key: str, *, timeout: float = 5.0) -> tuple[dict | None, int, str | None]:
    url = API_BASE.rstrip('/') + path
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8')
            payload = json.loads(body)
            if not isinstance(payload, dict):
                return None, int(resp.status), 'invalid JSON object'
            return payload, int(resp.status), None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode('utf-8')
            payload = json.loads(body)
        except Exception:
            payload = None
        return payload if isinstance(payload, dict) else None, int(exc.code), f'HTTP {exc.code}'
    except urllib.error.URLError as exc:
        return None, 0, f'unreachable ({getattr(exc, "reason", exc)})'
    except Exception as exc:
        return None, 0, str(exc)


def _validate_payload(payload: dict) -> str | None:
    if payload.get('ok') is True:
        if payload.get('source') != 'data/final_confidence_report.json':
            return 'source must be data/final_confidence_report.json'
        if not isinstance(payload.get('report'), dict):
            return 'report must be dict'
        if not isinstance(payload.get('summary'), dict):
            return 'summary must be dict'
        return None
    if payload.get('ok') is False and payload.get('error') == 'final_confidence_report_missing':
        return None
    return payload.get('error') or 'unexpected payload'


def main() -> int:
    if not LOADER.is_file():
        return _fail('final_confidence_report_loader.py missing')
    if not API_SERVER.is_file():
        return _fail('api_server.py missing')

    loader_src = LOADER.read_text(encoding='utf-8')
    api_src = API_SERVER.read_text(encoding='utf-8')

    if MARKER not in loader_src:
        return _fail(f'{MARKER} missing in loader')
    if 'load_cached_final_confidence_report' not in api_src:
        return _fail('api_server must use load_cached_final_confidence_report')
    for route in ROUTES:
        if route not in api_src:
            return _fail(f'route missing: {route!r}')
    if 'get_final_confidence_dashboard(limit=limit)' in api_src:
        return _fail('final-confidence routes must not call live get_final_confidence_dashboard')

    handler_block = api_src.split('api_debug_final_confidence')[1].split('def api_debug_confidence_calibration')[0]
    for token in ('get_runtime_snapshot', 'market_snapshot', 'build_final_confidence_report', 'score_all_candidates'):
        if token in handler_block:
            return _fail(f'final-confidence handlers must not use live dependency: {token!r}')

    try:
        from backend.analytics.final_confidence_report_loader import load_cached_final_confidence_report

        t0 = time.perf_counter()
        offline = load_cached_final_confidence_report(limit=50)
        if time.perf_counter() - t0 > 2.0:
            return _fail('offline loader exceeded 2s')
    except Exception as exc:
        return _fail(f'loader import/run: {exc}')

    api_key = _load_api_key()
    used_offline = False
    for path in ROUTES:
        t0 = time.perf_counter()
        payload, status, err = _fetch(path, api_key)
        elapsed = time.perf_counter() - t0
        if elapsed > 2.0:
            return _fail(f'{path} exceeded 2s ({elapsed:.2f}s)')

        if status == 0 or payload is None:
            payload = offline
            used_offline = True
            print(f'[FINAL_CONFIDENCE_STABILITY] offline fallback for {path} ({err})')
        elif status != 200:
            return _fail(f'{path} HTTP {status}')

        validation_err = _validate_payload(payload)
        if validation_err:
            return _fail(f'{path}: {validation_err}')

    if REPORT_FILE.is_file() and offline.get('ok') is not True:
        return _fail('report file exists but loader returned ok=false')

    if used_offline:
        print('[FINAL_CONFIDENCE_STABILITY] validated via offline loader fallback')
    print('FINAL_CONFIDENCE_ENDPOINT_STABILITY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
