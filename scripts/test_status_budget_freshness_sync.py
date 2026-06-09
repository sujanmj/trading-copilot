#!/usr/bin/env python3
"""Unit tests for /status budget freshness sync (Stage 48H)."""

from __future__ import annotations

import json
import os
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
    print(f'STATUS_BUDGET_FRESHNESS_SYNC_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _touch(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


def main() -> int:
    from backend.telegram.response_format import format_status_text

    ist = ZoneInfo('Asia/Kolkata')
    now_iso = datetime.now(ist).replace(microsecond=0).isoformat()

    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / 'data'
        data_root.mkdir()
        _touch(data_root / 'daily_report_pack_latest.json', {
            'generated_at': now_iso,
            'summary': {'market_mode': 'INDIA_MARKET_HOURS'},
        })
        _touch(data_root / 'scanner_data.json', {'generated_at': now_iso, 'session_date': '2026-06-08'})
        _touch(data_root / 'news_feed.json', {'updated_at': now_iso, 'articles': []})
        _touch(data_root / 'budget_impact_cache.json', {
            'ok': True,
            'generated_at': now_iso,
            'refreshed_at': now_iso,
            'stage': '48N',
            'top_catalysts': [],
            'top_themes': [],
        })
        _touch(data_root / 'theme_baskets.json', {
            'cache_refreshed_at': '2026-06-01T10:00:00+05:30',
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
        finally:
            dp.get_data_root = orig_root  # type: ignore[method-assign]
            lcr.DAILY_PACK_FILE = orig_pack

    if 'Latest budget cache:' not in text:
        return _fail('status missing Latest budget cache line')
    if 'Latest budget theme cache:' not in text:
        return _fail('status missing Latest budget theme cache line')
    if 'Latest theme cache:' in text:
        return _fail('status must not use legacy Latest theme cache label')

    budget_lines = [ln for ln in text.splitlines() if ln.startswith('Latest budget')]
    fresh_budget = [ln for ln in budget_lines if 'fresh' in ln.lower()]
    if len(fresh_budget) < 2:
        return _fail(f'expected fresh budget cache lines after refresh: {budget_lines!r}')

    if 'Legacy theme cache:' not in text:
        return _fail('status should show Legacy theme cache when theme_baskets exists')

    legacy_line = next((ln for ln in text.splitlines() if ln.startswith('Legacy theme cache:')), '')
    if 'stale' not in legacy_line.lower():
        return _fail(f'legacy theme cache should be stale: {legacy_line!r}')

    print('STATUS_BUDGET_FRESHNESS_SYNC_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
