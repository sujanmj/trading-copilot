#!/usr/bin/env python3
"""Unit tests for Telegram /status vs /budget freshness consistency (Stage 48K)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_FRESHNESS_CONSISTENCY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _touch(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


def main() -> int:
    from backend.analytics.budget_impact import format_budget_overview_telegram
    from backend.telegram.freshness_consistency import (
        BUDGET_CACHE_FRESH_THRESHOLD_MINUTES,
        classify_budget_cache_freshness,
    )
    from backend.telegram.response_format import format_status_text

    if classify_budget_cache_freshness(90) != 'fresh':
        return _fail('90m must be fresh')
    if classify_budget_cache_freshness(91) != 'stale':
        return _fail('91m must be stale')
    if classify_budget_cache_freshness(-1) != 'cache_missing':
        return _fail('missing age must be cache_missing')

    ist = ZoneInfo('Asia/Kolkata')
    stale_iso = (datetime.now(ist) - timedelta(minutes=100)).replace(microsecond=0).isoformat()

    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / 'data'
        data_root.mkdir()
        _touch(data_root / 'daily_report_pack_latest.json', {'generated_at': stale_iso, 'summary': {}})
        _touch(data_root / 'scanner_data.json', {'generated_at': stale_iso})
        _touch(data_root / 'news_feed.json', {'updated_at': stale_iso})
        _touch(data_root / 'budget_impact_cache.json', {
            'ok': True,
            'generated_at': stale_iso,
            'refreshed_at': stale_iso,
            'stage': '48O',
            'top_catalysts': [],
            'top_themes': [],
        })

        import backend.analytics.budget_impact as bi
        import backend.analytics.theme_baskets as tb
        import backend.storage.data_paths as dp
        import backend.telegram.lazy_command_runner as lcr

        orig_root = dp.get_data_root
        orig_pack = lcr.DAILY_PACK_FILE
        orig_cache = bi.CACHE_FILE
        orig_baskets = tb.BASKETS_FILE
        orig_get_data_path = bi.get_data_path
        dp.get_data_root = lambda: data_root  # type: ignore[method-assign]
        lcr.DAILY_PACK_FILE = data_root / 'daily_report_pack_latest.json'
        bi.CACHE_FILE = data_root / 'budget_impact_cache.json'
        tb.BASKETS_FILE = data_root / 'theme_baskets.json'
        _touch(data_root / 'theme_baskets.json', {'cache_refreshed_at': stale_iso, 'baskets': []})

        def _temp_data_path(rel: str) -> Path:
            return data_root / rel

        bi.get_data_path = _temp_data_path  # type: ignore[method-assign]

        try:
            status_text = format_status_text()
            budget_text = format_budget_overview_telegram()
        finally:
            dp.get_data_root = orig_root  # type: ignore[method-assign]
            lcr.DAILY_PACK_FILE = orig_pack
            bi.CACHE_FILE = orig_cache
            tb.BASKETS_FILE = orig_baskets
            bi.get_data_path = orig_get_data_path  # type: ignore[method-assign]

    budget_line = next(
        (ln for ln in status_text.splitlines() if ln.startswith('Latest budget cache:')),
        '',
    )
    if 'stale' not in budget_line.lower():
        return _fail(f'status budget cache should be stale at 100m: {budget_line!r}')
    if 'Freshness: <code>stale</code>' not in budget_text:
        return _fail(f'budget overview must show stale freshness: {budget_text!r}')
    if str(BUDGET_CACHE_FRESH_THRESHOLD_MINUTES) not in '90':
        return _fail('threshold must be 90 minutes')

    print('TELEGRAM_FRESHNESS_CONSISTENCY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
