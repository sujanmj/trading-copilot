#!/usr/bin/env python3
"""
Post-deploy smoke checks against a live Railway web service (Stage 46B).

Usage:
  python scripts/railway_post_deploy_smoke.py --base-url https://YOUR-RAILWAY-APP.up.railway.app
  python scripts/railway_post_deploy_smoke.py --base-url https://YOUR-APP.up.railway.app --api-key YOUR_KEY

Prints RAILWAY_POST_DEPLOY_SMOKE_OK on success.
Does not print secret values.
"""

from __future__ import annotations

import argparse
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

STAGE_MARKER = 'RAILWAY_STAGE_46B_POST_DEPLOY_SMOKE'

ENDPOINTS = (
    ('health', '/api/health'),
    ('final_confidence', '/api/debug/final-confidence'),
    ('daily_report_pack', '/api/debug/daily-report-pack'),
    ('stock_decision_today', '/api/debug/stock-decision?mode=today'),
    ('stock_decision_tomorrow', '/api/debug/stock-decision?mode=tomorrow'),
    ('aihub_brain', '/api/debug/aihub-tab/brain'),
    ('aihub_scan', '/api/debug/aihub-tab/scan'),
    ('aihub_market', '/api/debug/aihub-tab/market'),
)


def _fail(msg: str) -> int:
    print(f'RAILWAY_POST_DEPLOY_SMOKE_FAIL: {msg}', file=sys.stderr)
    return 1


def _load_api_key(cli_key: str | None) -> str:
    if cli_key and cli_key.strip():
        return cli_key.strip()
    env_key = os.environ.get('API_KEY', '').strip()
    if env_key:
        return env_key
    try:
        from backend.utils.config import get_env, load_env

        load_env()
        return get_env('API_KEY')
    except Exception:
        return ''


def _normalize_base_url(raw: str) -> str:
    url = raw.strip().rstrip('/')
    if not url.startswith('http://') and not url.startswith('https://'):
        url = f'https://{url}'
    return url


def _fetch_json(base_url: str, path: str, api_key: str) -> tuple[dict | None, int | None, str | None]:
    url = base_url.rstrip('/') + path
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.getcode()
            content_type = (resp.headers.get('Content-Type') or '').lower()
            body = resp.read().decode('utf-8', errors='replace')
            if 'text/html' in content_type and '<html' in body.lower():
                return None, status, 'response is HTML not JSON'
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return None, status, 'response is not valid JSON'
            if not isinstance(payload, dict):
                return None, status, 'JSON root is not an object'
            return payload, status, None
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode('utf-8', errors='replace')[:200]
        except Exception:
            detail = str(exc)
        if 'text/html' in (exc.headers.get('Content-Type') or '').lower():
            return None, exc.code, 'HTTP error returned HTML'
        return None, exc.code, f'HTTP {exc.code}: {detail}'
    except urllib.error.URLError as exc:
        return None, None, f'not reachable ({getattr(exc, "reason", exc)})'
    except Exception as exc:
        return None, None, str(exc)


def run_smoke(base_url: str, api_key: str) -> str | None:
    for label, path in ENDPOINTS:
        payload, status, err = _fetch_json(base_url, path, api_key)
        ok = err is None and status is not None and status != 500
        print(f'[RAILWAY_POST_DEPLOY] {label}={ "ok" if ok else "fail" } status={status}')
        if status == 500:
            return f'{label} returned HTTP 500'
        if err:
            return f'{label}: {err}'
        if payload is None:
            return f'{label}: empty payload'
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description='Post-deploy smoke against Railway web API.')
    parser.add_argument(
        '--base-url',
        required=True,
        help='Railway web base URL, e.g. https://YOUR-APP.up.railway.app',
    )
    parser.add_argument(
        '--api-key',
        default=None,
        help='HTTP API key (optional; falls back to API_KEY env or keys.env locally)',
    )
    args = parser.parse_args()

    base_url = _normalize_base_url(args.base_url)
    api_key = _load_api_key(args.api_key)

    print(f'[RAILWAY_POST_DEPLOY] base_url={base_url}')
    print(f'[RAILWAY_POST_DEPLOY] auth={"yes" if api_key else "no"}')

    err = run_smoke(base_url, api_key)
    if err:
        return _fail(err)

    print(STAGE_MARKER)
    print('RAILWAY_POST_DEPLOY_SMOKE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
