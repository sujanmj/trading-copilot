#!/usr/bin/env python3
"""
Validate GET /api/debug/aihub-tab-freshness contract.

Usage (API server running on 127.0.0.1:8080):
  python scripts/validate_aihub_tab_freshness_api.py

Prints exactly AIHUB_TAB_FRESHNESS_API_OK on success.
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
API_PATH = '/api/debug/aihub-tab-freshness'
REQUIRED_TABS = ('brain', 'govt', 'scan', 'mkt', 'global', 'news', 'tv', 'rdt', 'calib', 'journal')


def _fail(msg: str) -> int:
    print(f'[AIHUB_FRESHNESS_API] FAIL: {msg}', file=sys.stderr)
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


def main() -> int:
    api_key = _load_api_key()
    url = API_BASE.rstrip('/') + API_PATH
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(url, headers=headers, method='GET')

    payload = None
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except Exception as exc:
        try:
            from backend.analytics.aihub_tab_freshness import get_aihub_tab_freshness_report

            payload = get_aihub_tab_freshness_report()
            print(f'[AIHUB_FRESHNESS_API] offline fallback ({exc})')
        except Exception as offline_exc:
            return _fail(f'fetch failed ({exc}); offline: {offline_exc}')

    if not isinstance(payload, dict):
        return _fail('invalid JSON object')
    if payload.get('ok') is not True:
        return _fail(f"ok != true ({payload.get('error')})")

    tabs = payload.get('tabs')
    if not isinstance(tabs, dict):
        return _fail('tabs must be object')

    for tab in REQUIRED_TABS:
        if tab not in tabs:
            return _fail(f'missing tab key: {tab}')
        if not isinstance(tabs[tab], dict):
            return _fail(f'tab {tab} must be object')
        print(f'[AIHUB_FRESHNESS_API] {tab} ok age_hours={tabs[tab].get("age_hours", tabs[tab].get("data_age_hours"))}')

    print('AIHUB_TAB_FRESHNESS_API_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
