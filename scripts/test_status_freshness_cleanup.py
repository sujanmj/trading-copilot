#!/usr/bin/env python3
"""Unit tests for /status freshness line cleanup (Stage 47F)."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'STATUS_FRESHNESS_CLEANUP_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _touch(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


def _line_has_single_fresh_stale(line: str) -> bool:
    lower = line.lower()
    fresh_count = lower.count('fresh')
    stale_count = lower.count('stale')
    status_tokens = fresh_count + stale_count
    if status_tokens == 0:
        return True
    if fresh_count > 0 and stale_count > 0:
        return False
    return status_tokens == 1


def main() -> int:
    from backend.telegram.response_format import _format_feed_freshness_line, format_status_text

    ist = ZoneInfo('Asia/Kolkata')
    now_iso = datetime.now(ist).replace(microsecond=0).isoformat()
    utc_iso = datetime.now(ZoneInfo('UTC')).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / 'data'
        data_root.mkdir()
        _touch(data_root / 'daily_report_pack_latest.json', {
            'generated_at': now_iso,
            'summary': {'market_mode': 'INDIA_MARKET_HOURS'},
        })
        _touch(data_root / 'scanner_data.json', {'generated_at': utc_iso, 'session_date': '2026-06-08'})
        _touch(data_root / 'news_feed.json', {'updated_at': now_iso, 'articles': []})
        _touch(data_root / 'theme_baskets.json', {
            'cache_refreshed_at': now_iso,
            'theme_schema_version': '47F',
            'baskets': [],
            'stage': '47F',
        })

        import backend.storage.data_paths as dp
        import backend.telegram.lazy_command_runner as lcr

        orig_root = dp.get_data_root
        orig_pack = lcr.DAILY_PACK_FILE
        dp.get_data_root = lambda: data_root  # type: ignore[method-assign]
        lcr.DAILY_PACK_FILE = data_root / 'daily_report_pack_latest.json'

        try:
            text = format_status_text()
            theme_line = _format_feed_freshness_line(
                'Latest theme cache',
                data_root / 'theme_baskets.json',
            )
        finally:
            dp.get_data_root = orig_root  # type: ignore[method-assign]
            lcr.DAILY_PACK_FILE = orig_pack

    if 'AstraEdge 48C' not in text:
        return _fail('status missing AstraEdge 48C build line')

    for label in ('Latest report:', 'Latest scanner:', 'Latest news:', 'Latest theme cache:'):
        if label not in text:
            return _fail(f'status missing {label!r}')

    for line in text.splitlines():
        if any(line.startswith(prefix) for prefix in (
            'Latest report:',
            'Latest scanner:',
            'Latest news:',
            'Latest theme cache:',
        )):
            if not _line_has_single_fresh_stale(line):
                return _fail(f'line has mixed fresh/stale: {line!r}')

    if 'fresh ·' in theme_line and 'stale' in theme_line.lower().split('·')[-1]:
        return _fail('theme freshness line still mixes fresh age label with stale status')

    if not re.search(r'age \d+[mh]', theme_line):
        return _fail(f'theme line missing age token: {theme_line!r}')

    print('STATUS_FRESHNESS_CLEANUP_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
