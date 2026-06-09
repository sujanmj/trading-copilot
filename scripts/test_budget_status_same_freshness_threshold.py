#!/usr/bin/env python3
"""Unit tests — /status and /budget share 90m freshness threshold (Stage 48K)."""

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
    print(f'BUDGET_STATUS_SAME_FRESHNESS_THRESHOLD_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _touch(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


def main() -> int:
    from backend.analytics.budget_impact import compute_freshness_panel, format_budget_overview_telegram
    from backend.telegram.freshness_consistency import classify_budget_cache_freshness
    from backend.telegram.response_format import format_status_text

    ist = ZoneInfo('Asia/Kolkata')
    fresh_iso = (datetime.now(ist) - timedelta(minutes=45)).replace(microsecond=0).isoformat()

    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / 'data'
        data_root.mkdir()
        _touch(data_root / 'daily_report_pack_latest.json', {'generated_at': fresh_iso, 'summary': {}})
        _touch(data_root / 'scanner_data.json', {'generated_at': fresh_iso})
        _touch(data_root / 'news_feed.json', {'updated_at': fresh_iso})
        _touch(data_root / 'budget_impact_cache.json', {
            'ok': True,
            'generated_at': fresh_iso,
            'refreshed_at': fresh_iso,
            'stage': '48O',
        })

        import backend.analytics.budget_impact as bi
        import backend.storage.data_paths as dp
        import backend.telegram.lazy_command_runner as lcr

        orig_root = dp.get_data_root
        orig_pack = lcr.DAILY_PACK_FILE
        orig_cache = bi.CACHE_FILE
        dp.get_data_root = lambda: data_root  # type: ignore[method-assign]
        lcr.DAILY_PACK_FILE = data_root / 'daily_report_pack_latest.json'
        bi.CACHE_FILE = data_root / 'budget_impact_cache.json'

        try:
            panel = compute_freshness_panel()
            status_text = format_status_text()
            budget_text = format_budget_overview_telegram()
        finally:
            dp.get_data_root = orig_root  # type: ignore[method-assign]
            lcr.DAILY_PACK_FILE = orig_pack
            bi.CACHE_FILE = orig_cache

    expected = classify_budget_cache_freshness(45)
    if panel.get('budget_cache', {}).get('status') != expected:
        return _fail(f"budget_cache status mismatch: {panel.get('budget_cache')}")
    if panel.get('theme_cache', {}).get('status') != expected:
        return _fail(f"theme_cache status mismatch: {panel.get('theme_cache')}")
    if panel.get('status') != expected:
        return _fail(f"panel status mismatch: {panel.get('status')}")

    status_budget = [
        ln for ln in status_text.splitlines()
        if ln.startswith('Latest budget cache:') or ln.startswith('Latest budget theme cache:')
    ]
    if len(status_budget) < 2:
        return _fail('status missing budget cache lines')
    if any('fresh' not in ln.lower() for ln in status_budget):
        return _fail(f'status budget lines should be fresh at 45m: {status_budget!r}')
    if f'Freshness: <code>{expected}</code>' not in budget_text:
        return _fail(f'budget overview freshness mismatch: {budget_text!r}')

    print('BUDGET_STATUS_SAME_FRESHNESS_THRESHOLD_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
