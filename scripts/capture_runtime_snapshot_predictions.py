#!/usr/bin/env python3
"""
Capture active_predictions from /api/runtime/snapshot into canonical_market_memory.db.

Usage:
  python scripts/capture_runtime_snapshot_predictions.py [--dry-run] [--limit N]
      [--verbose] [--source api|file|auto] [--update-existing]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

API_BASE = 'http://127.0.0.1:8080'
API_PATH = '/api/runtime/snapshot'
ACTIVE_SNAPSHOT_FILE = PROJECT_ROOT / 'data' / 'active_snapshot.json'

try:
    from backend.utils.config import RUNTIME_SNAPSHOT_CACHE
except Exception:
    RUNTIME_SNAPSHOT_CACHE = PROJECT_ROOT / 'data' / 'cache' / 'runtime_snapshot.json'

from backend.storage.market_memory_capture import (  # noqa: E402
    capture_predictions,
    normalize_prediction_payload,
)
from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db  # noqa: E402
from backend.storage.runtime_snapshot_capture import (  # noqa: E402
    SOURCE_HINT,
    apply_snapshot_timestamps,
    extract_runtime_snapshot_predictions,
    extract_snapshot_published_at,
    extract_ticker,
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


def _fetch_api_snapshot(api_key: str = '', *, auth_retried: bool = False) -> tuple[dict | None, str | None]:
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
            return _fetch_api_snapshot(api_key=retry_key, auth_retried=True)
        try:
            detail = exc.read().decode('utf-8', errors='replace')[:200]
        except Exception:
            detail = str(exc)
        return None, f'HTTP {exc.code}: {detail}'
    except urllib.error.URLError as exc:
        return None, str(getattr(exc, 'reason', exc))
    except json.JSONDecodeError as exc:
        return None, f'invalid JSON: {exc}'
    except Exception as exc:
        return None, str(exc)


def _load_json_file(path: Path) -> tuple[dict | None, str | None]:
    if not path.is_file():
        return None, 'missing'
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, 'invalid JSON object'
    return payload, None


def _load_active_snapshot() -> tuple[dict | None, str | None]:
    return _load_json_file(ACTIVE_SNAPSHOT_FILE)


def _resolve_snapshots(source: str, api_key: str) -> tuple[dict | None, dict | None, str]:
    file_snapshot, file_err = _load_active_snapshot()

    if source == 'file':
        if file_snapshot is None:
            raise RuntimeError(f'active_snapshot.json unavailable: {file_err}')
        return None, file_snapshot, 'file:active_snapshot.json'

    if source == 'api':
        api_snapshot, api_err = _fetch_api_snapshot(api_key=api_key)
        if api_snapshot is None:
            raise RuntimeError(f'API unavailable: {api_err}')
        return api_snapshot, file_snapshot, 'api:/api/runtime/snapshot'

    api_snapshot, api_err = _fetch_api_snapshot(api_key=api_key)
    if api_snapshot is not None:
        return api_snapshot, file_snapshot, 'api:/api/runtime/snapshot'

    if file_snapshot is not None:
        return None, file_snapshot, 'file:active_snapshot.json'

    cache_snapshot, cache_err = _load_json_file(Path(RUNTIME_SNAPSHOT_CACHE))
    if cache_snapshot is not None:
        return cache_snapshot, file_snapshot, 'file:cache/runtime_snapshot.json'

    raise RuntimeError(
        f'API unavailable ({api_err}); active_snapshot.json unavailable ({file_err}); '
        f'runtime snapshot cache unavailable ({cache_err})'
    )


def _maybe_upgrade_to_cache_snapshot(
    api_snapshot: dict | None,
    file_snapshot: dict | None,
    load_source: str,
    candidates: list[Any],
    candidate_source: str | None,
) -> tuple[dict | None, str, list[Any], str | None]:
    """When active_snapshot fallback has no predictions, try cached runtime snapshot."""
    if candidates or load_source != 'file:active_snapshot.json':
        return api_snapshot, load_source, candidates, candidate_source

    cache_snapshot, _ = _load_json_file(Path(RUNTIME_SNAPSHOT_CACHE))
    if cache_snapshot is None:
        return api_snapshot, load_source, candidates, candidate_source

    cache_candidates, cache_source = extract_runtime_snapshot_predictions(
        cache_snapshot,
        file_snapshot=file_snapshot,
    )
    if not cache_candidates:
        return api_snapshot, load_source, candidates, candidate_source

    return cache_snapshot, 'file:cache/runtime_snapshot.json', cache_candidates, cache_source


def _sample_tickers(items: list[Any], limit: int = 5) -> list[str]:
    tickers: list[str] = []
    for item in items:
        ticker = extract_ticker(item)
        if ticker and ticker not in tickers:
            tickers.append(ticker)
        if len(tickers) >= limit:
            break
    return tickers


def _count_normalizable(items: list[dict]) -> int:
    count = 0
    for item in items:
        if normalize_prediction_payload(item, source_hint=SOURCE_HINT) is not None:
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description='Capture runtime snapshot active predictions.')
    parser.add_argument('--dry-run', action='store_true', help='Print summary without DB writes')
    parser.add_argument('--limit', type=int, default=0, help='Max candidates to process (0 = all)')
    parser.add_argument('--verbose', action='store_true', help='Verbose stderr logging')
    parser.add_argument(
        '--source',
        choices=('auto', 'api', 'file'),
        default='auto',
        help='Snapshot source: api, file:active_snapshot.json, or auto (default)',
    )
    parser.add_argument(
        '--update-existing',
        action='store_true',
        help=(
            'Refresh existing prediction rows on conflict (upsert_prediction updates '
            'legacy IDs with improved direction/signal_stack)'
        ),
    )
    args = parser.parse_args()

    api_key = _load_api_key()
    try:
        api_snapshot, file_snapshot, load_source = _resolve_snapshots(args.source, api_key)
    except RuntimeError as exc:
        print(f'[RUNTIME_CAPTURE] error={exc}', file=sys.stderr)
        return 1

    candidates, candidate_source = extract_runtime_snapshot_predictions(
        api_snapshot,
        file_snapshot=file_snapshot,
    )
    api_snapshot, load_source, candidates, candidate_source = _maybe_upgrade_to_cache_snapshot(
        api_snapshot,
        file_snapshot,
        load_source,
        candidates,
        candidate_source,
    )
    if candidate_source is None:
        candidate_source = 'none'

    snapshot_for_ts = api_snapshot or file_snapshot or {}
    snapshot_ts = extract_snapshot_published_at(snapshot_for_ts)
    prepared = apply_snapshot_timestamps(candidates, snapshot_ts)

    if args.limit and args.limit > 0:
        prepared = prepared[: args.limit]

    source_label = f'{load_source}:{candidate_source}'
    candidates_found = len(candidates)
    sample = _sample_tickers(prepared)

    if args.verbose:
        print(
            f'[RUNTIME_CAPTURE] load_source={load_source} candidate_source={candidate_source} '
            f'snapshot_ts={snapshot_ts} update_existing={args.update_existing}',
            file=sys.stderr,
        )

    if args.dry_run:
        would_capture = _count_normalizable(prepared)
        print(f'[RUNTIME_CAPTURE] source={source_label}')
        print(f'[RUNTIME_CAPTURE] candidates_found={candidates_found}')
        print(f'[RUNTIME_CAPTURE] candidates_would_capture={would_capture}')
        print(f'[RUNTIME_CAPTURE] sample_tickers={sample}')
        return 0

    if not init_market_memory_db():
        print('[RUNTIME_CAPTURE] error=init_market_memory_db failed', file=sys.stderr)
        return 1

    summary = capture_predictions(prepared, source_hint=SOURCE_HINT)
    captured = int(summary.get('captured') or 0)
    skipped = int(summary.get('skipped') or 0)
    attempted = int(summary.get('attempted') or 0)
    failed = max(0, attempted - captured - skipped)
    stats = get_market_memory_stats()

    print(f'[RUNTIME_CAPTURE] source={source_label}')
    print(f'[RUNTIME_CAPTURE] update_existing={args.update_existing}')
    print(f'[RUNTIME_CAPTURE] candidates_found={candidates_found}')
    print(f'[RUNTIME_CAPTURE] captured={captured}')
    print(f'[RUNTIME_CAPTURE] skipped={skipped}')
    print(f'[RUNTIME_CAPTURE] failed={failed}')
    print(f'[RUNTIME_CAPTURE] stats={json.dumps(stats, default=str)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
