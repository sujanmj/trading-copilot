#!/usr/bin/env python3
"""
Inspect files/endpoints feeding runtime snapshot API and AI Hub cache.

Usage:
  python scripts/inspect_runtime_snapshot_sources.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

API_BASE = 'http://127.0.0.1:8080'
ENDPOINTS = ('/api/runtime/snapshot', '/api/runtime_snapshot')

CANDIDATE_FILES = (
    'cache/runtime_snapshot.json',
    'active_snapshot.json',
    'runtime/current_snapshot.json',
    'unified_intelligence.json',
    'orchestrator_state.json',
    'analysis_state.json',
    'latest_market_data.json',
    'scanner_data.json',
    'stats_data.json',
    'history_data.json',
)


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


def _fetch_snapshot(path: str, api_key: str = '', *, auth_retried: bool = False) -> tuple[Optional[dict], Optional[str]]:
    url = f"{API_BASE.rstrip('/')}{path}?_ts=1"
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
            return (payload if isinstance(payload, dict) else None), None
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) and not auth_retried:
            return _fetch_snapshot(path, api_key=_load_api_key(), auth_retried=True)
        return None, f'HTTP {exc.code}'
    except urllib.error.URLError as exc:
        return None, str(getattr(exc, 'reason', exc))
    except Exception as exc:
        return None, str(exc)


def _file_mtime_iso(rel_path: str) -> tuple[Optional[str], bool]:
    path = PROJECT_ROOT / 'data' / rel_path
    if not path.is_file():
        return None, False
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(), True
    except Exception:
        return None, True


def main() -> int:
    from backend.utils.config import DATA_DIR, RUNTIME_SNAPSHOT_CACHE

    api_key = _load_api_key()
    api_payload: Optional[dict] = None
    api_err: Optional[str] = None

    for endpoint in ENDPOINTS:
        payload, err = _fetch_snapshot(endpoint, api_key=api_key)
        if payload is not None:
            api_payload = payload
            stale = (payload.get('freshness') or {}).get('stale')
            print(f'[RUNTIME_SOURCES] endpoint={endpoint} snapshot_id={payload.get("snapshot_id")}')
            print(f'[RUNTIME_SOURCES] generated_at={payload.get("generated_at")}')
            print(f'[RUNTIME_SOURCES] package_generated_at={payload.get("package_generated_at")}')
            print(f'[RUNTIME_SOURCES] data_as_of={payload.get("data_as_of")}')
            print(f'[RUNTIME_SOURCES] stale={stale}')
            break
        api_err = err

    if api_payload is None:
        print(f'[RUNTIME_SOURCES] endpoint=/api/runtime/snapshot snapshot_id=unavailable error={api_err}')
        cache_path = RUNTIME_SNAPSHOT_CACHE
        if cache_path.is_file():
            try:
                api_payload = json.loads(cache_path.read_text(encoding='utf-8'))
                print(f'[RUNTIME_SOURCES] endpoint=offline_cache snapshot_id={api_payload.get("snapshot_id")}')
                print(f'[RUNTIME_SOURCES] generated_at={api_payload.get("generated_at")}')
                print(f'[RUNTIME_SOURCES] stale={(api_payload.get("freshness") or {}).get("stale")}')
            except Exception as exc:
                print(f'[RUNTIME_SOURCES] offline_cache_error={exc}')

    candidate_files: list[str] = []
    newest_path: Optional[str] = None
    newest_mtime: Optional[str] = None
    newest_ts = 0.0

    for rel in CANDIDATE_FILES:
        if rel.startswith('cache/'):
            path = DATA_DIR.parent / 'data' / rel if rel == 'cache/runtime_snapshot.json' else RUNTIME_SNAPSHOT_CACHE
            if rel == 'cache/runtime_snapshot.json':
                path = RUNTIME_SNAPSHOT_CACHE
        elif rel.startswith('runtime/'):
            path = DATA_DIR / rel.replace('runtime/', 'runtime/')
        else:
            path = DATA_DIR / rel

        if path.is_file():
            candidate_files.append(str(path))
            mtime_iso = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            print(f'[RUNTIME_SOURCES] source_file={path} mtime={mtime_iso}')
            mtime_val = path.stat().st_mtime
            if mtime_val >= newest_ts:
                newest_ts = mtime_val
                newest_path = str(path)
                newest_mtime = mtime_iso

    print(f'[RUNTIME_SOURCES] candidate_files={candidate_files}')
    print(f'[RUNTIME_SOURCES] newest_source_file={newest_path}')
    print(f'[RUNTIME_SOURCES] newest_source_mtime={newest_mtime}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
