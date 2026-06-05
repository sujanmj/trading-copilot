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


def _parse_build_stage(stage: str) -> tuple[int, int] | None:
    """Parse build stage like 46E, 47A, 47B, 48A → (numeric, letter_ord)."""
    import re

    raw = str(stage or '').strip().upper()
    match = re.match(r'^(\d+)([A-Z])$', raw)
    if not match:
        return None
    return int(match.group(1)), ord(match.group(2))


def _stage_at_least(min_stage: str, actual: str) -> bool:
    """Compare stages: numeric part first, then letter (46E minimum)."""
    min_parsed = _parse_build_stage(min_stage)
    act_parsed = _parse_build_stage(actual)
    if not min_parsed or not act_parsed:
        return False
    if act_parsed[0] != min_parsed[0]:
        return act_parsed[0] > min_parsed[0]
    return act_parsed[1] >= min_parsed[1]


def _stage_at_least_46e(stage: str) -> bool:
    return _stage_at_least('46E', stage)


def _validate_build_info(payload: dict) -> str | None:
    if payload.get('app') != 'AstraEdge':
        return f"app must be AstraEdge, got {payload.get('app')!r}"
    stage = str(payload.get('stage') or '')
    if not _stage_at_least_46e(stage):
        return f'stage must be at least 46E, got {stage!r}'
    if payload.get('telegram_handler') != 'astraedge_analysis_bot':
        return 'telegram_handler must be astraedge_analysis_bot'
    if payload.get('legacy_telegram_listener') is not False:
        return 'legacy_telegram_listener must be false'
    data_root = str(payload.get('data_root') or '').replace('\\', '/')
    if data_root != '/app/data':
        return f'data_root must be /app/data, got {data_root!r}'
    if payload.get('data_preserved') is not True:
        return 'data_preserved must be true'
    return None


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


def run_smoke(base_url: str, api_key: str, *, strict_build_info: bool = False) -> str | None:
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

    if strict_build_info:
        payload, status, err = _fetch_json(base_url, '/api/debug/build-info', api_key)
        print(f'[RAILWAY_POST_DEPLOY] build_info={"ok" if err is None else "fail"} status={status}')
        if err:
            return f'build-info: {err}'
        if payload is None:
            return 'build-info: empty payload'
        build_err = _validate_build_info(payload)
        if build_err:
            return f'build-info: {build_err}'
        print(
            '[RAILWAY_POST_DEPLOY] build_info '
            f'stage={payload.get("stage")} '
            f'telegram_started={payload.get("astraedge_telegram_started")}'
        )

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
    parser.add_argument(
        '--strict-build-info',
        action='store_true',
        help='Validate /api/debug/build-info stage 46E fields',
    )
    args = parser.parse_args()

    base_url = _normalize_base_url(args.base_url)
    api_key = _load_api_key(args.api_key)

    print(f'[RAILWAY_POST_DEPLOY] base_url={base_url}')
    print(f'[RAILWAY_POST_DEPLOY] auth={"yes" if api_key else "no"}')
    print(f'[RAILWAY_POST_DEPLOY] strict_build_info={"yes" if args.strict_build_info else "no"}')

    err = run_smoke(base_url, api_key, strict_build_info=args.strict_build_info)
    if err:
        return _fail(err)

    print(STAGE_MARKER)
    print('RAILWAY_POST_DEPLOY_SMOKE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
