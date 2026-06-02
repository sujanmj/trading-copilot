#!/usr/bin/env python3
"""
Inspect local external source JSON files for broker/app collector.

Prints [EXT_SOURCE_FILE] lines and EXTERNAL_SOURCE_FILES_OK.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.utils.config import DATA_DIR

SOURCE_FILES = (
    'news_feed.json',
    'live_news_feed.json',
    'tv_intelligence.json',
    'broker_app_collector_latest.json',
    'broker_prediction_inbox.json',
    'latest_market_data.json',
    'historical_ticker_universe.json',
)

TITLE_KEYS = ('title', 'headline', 'name', 'summary', 'description', 'text')
TICKER_KEYS = ('ticker', 'symbol', 'tickers', 'symbols', 'tags', 'topics')
CONTAINER_KEYS = ('items', 'articles', 'news', 'headlines', 'data', 'results', 'feed', 'entries', 'videos')


def _fail(msg: str) -> int:
    print(f'EXTERNAL_SOURCE_FILES_FAIL: {msg}', file=sys.stderr)
    return 1


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        val = row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ''


def _walk_records(data: Any, depth: int = 0, max_depth: int = 3) -> list[dict[str, Any]]:
    if depth > max_depth:
        return []
    if isinstance(data, list):
        rows: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                rows.append(item)
            elif isinstance(item, list):
                rows.extend(_walk_records(item, depth + 1, max_depth))
        return rows
    if not isinstance(data, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in CONTAINER_KEYS:
        child = data.get(key)
        if isinstance(child, list):
            rows.extend(row for row in child if isinstance(row, dict))
        elif isinstance(child, dict):
            rows.extend(_walk_records(child, depth + 1, max_depth))
    source_meta = data.get('source_meta')
    if isinstance(source_meta, dict):
        rows.extend(_walk_records(source_meta, depth + 1, max_depth))
    return rows


def _headline_like_count(records: list[dict[str, Any]]) -> int:
    count = 0
    for row in records:
        title = _first_text(row, TITLE_KEYS)
        if title:
            count += 1
    return count


def _ticker_like_count(records: list[dict[str, Any]]) -> int:
    count = 0
    token_re = re.compile(r'^[A-Z0-9&.\-]{3,20}$')
    for row in records:
        found = False
        for key in TICKER_KEYS:
            val = row.get(key)
            if isinstance(val, list):
                if any(token_re.match(str(v).strip().upper()) for v in val if v is not None):
                    found = True
                    break
            elif val is not None and token_re.match(str(val).strip().upper()):
                found = True
                break
        if not found:
            title = _first_text(row, TITLE_KEYS)
            body = _first_text(row, ('description', 'summary', 'text', 'notes'))
            if re.search(r'\b[A-Z]{3,12}\b', f'{title} {body}'):
                found = True
        if found:
            count += 1
    return count


def _sample_titles(records: list[dict[str, Any]], limit: int = 5) -> list[str]:
    titles: list[str] = []
    for row in records:
        title = _first_text(row, TITLE_KEYS)
        if title:
            titles.append(title[:100])
        if len(titles) >= limit:
            break
    return titles


def _safe_console(text: str) -> str:
    return str(text).encode('ascii', 'replace').decode('ascii')


def inspect_file(rel_name: str) -> None:
    path = DATA_DIR / rel_name
    print(f'[EXT_SOURCE_FILE] file={path}')
    print(f'[EXT_SOURCE_FILE] exists={path.is_file()}')
    if not path.is_file():
        print('[EXT_SOURCE_FILE] type=missing')
        print('[EXT_SOURCE_FILE] top_keys=[]')
        print('[EXT_SOURCE_FILE] item_count=0')
        print('[EXT_SOURCE_FILE] headline_like_count=0')
        print('[EXT_SOURCE_FILE] ticker_like_count=0')
        print('[EXT_SOURCE_FILE] sample_titles=[]')
        return

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        print('[EXT_SOURCE_FILE] type=invalid_json')
        print(f'[EXT_SOURCE_FILE] top_keys=[error:{exc}]')
        print('[EXT_SOURCE_FILE] item_count=0')
        print('[EXT_SOURCE_FILE] headline_like_count=0')
        print('[EXT_SOURCE_FILE] ticker_like_count=0')
        print('[EXT_SOURCE_FILE] sample_titles=[]')
        return

    if isinstance(data, dict):
        root_type = 'dict'
        top_keys = sorted(str(k) for k in data.keys())
        records = _walk_records(data)
        if not records and 'tickers' in data:
            records = [row for row in (data.get('tickers') or []) if isinstance(row, dict)]
    elif isinstance(data, list):
        root_type = 'list'
        top_keys = []
        records = [row for row in data if isinstance(row, dict)]
    else:
        root_type = type(data).__name__
        top_keys = []
        records = []

    print(f'[EXT_SOURCE_FILE] type={root_type}')
    print(f'[EXT_SOURCE_FILE] top_keys={top_keys[:20]}')
    print(f'[EXT_SOURCE_FILE] item_count={len(records)}')
    print(f'[EXT_SOURCE_FILE] headline_like_count={_headline_like_count(records)}')
    print(f'[EXT_SOURCE_FILE] ticker_like_count={_ticker_like_count(records)}')
    print(f'[EXT_SOURCE_FILE] sample_titles={[_safe_console(t) for t in _sample_titles(records)]}')


def main() -> int:
    for rel_name in SOURCE_FILES:
        inspect_file(rel_name)
    print('EXTERNAL_SOURCE_FILES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
