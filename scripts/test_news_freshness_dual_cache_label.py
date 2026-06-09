#!/usr/bin/env python3
"""Unit tests — dual news cache freshness labels (Stage 48R)."""

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

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'NEWS_FRESHNESS_DUAL_CACHE_LABEL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _touch(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


def main() -> int:
    from backend.telegram.freshness_consistency import (
        format_compact_freshness_line,
        get_news_freshness_dual,
    )
    from backend.telegram.lazy_command_runner import run_news_only

    ist = ZoneInfo('Asia/Kolkata')
    fresh_iso = (datetime.now(ist) - timedelta(minutes=5)).replace(microsecond=0).isoformat()
    stale_iso = (datetime.now(ist) - timedelta(hours=6)).replace(microsecond=0).isoformat()

    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / 'data'
        data_root.mkdir()
        _touch(data_root / 'news_feed.json', {'updated_at': fresh_iso, 'articles': []})
        _touch(
            data_root / 'daily_report_pack_latest.json',
            {
                'generated_at': stale_iso,
                'news': {'generated_at': stale_iso, 'items': []},
                'summary': {},
            },
        )

        import backend.storage.data_paths as dp
        import backend.telegram.lazy_command_runner as lcr

        orig_root = dp.get_data_root
        orig_pack = lcr.DAILY_PACK_FILE
        dp.get_data_root = lambda: data_root  # type: ignore[method-assign]
        lcr.DAILY_PACK_FILE = data_root / 'daily_report_pack_latest.json'

        try:
            dual = get_news_freshness_dual()
            news_text = run_news_only(refresh=False).get('text') or ''
        finally:
            dp.get_data_root = orig_root  # type: ignore[method-assign]
            lcr.DAILY_PACK_FILE = orig_pack

    latest_line = dual.get('latest_line', '')
    report_line = dual.get('report_line', '')
    if not latest_line.startswith('Latest news cache:'):
        return _fail(f'latest_line must use Latest news cache label: {latest_line!r}')
    if not report_line.startswith('Report news cache:'):
        return _fail(f'report_line must use Report news cache label: {report_line!r}')
    if dual.get('latest_status') != 'fresh':
        return _fail(f'latest news cache should be fresh at 5m: {dual!r}')
    if dual.get('report_status') != 'stale':
        return _fail(f'report news cache should be stale at 6h: {dual!r}')

    expected_latest = format_compact_freshness_line('Latest news cache', dual.get('latest_age_min', -1))
    expected_report = format_compact_freshness_line('Report news cache', dual.get('report_age_min', -1))
    if latest_line != expected_latest:
        return _fail(f'latest_line mismatch: {latest_line!r} vs {expected_latest!r}')
    if report_line != expected_report:
        return _fail(f'report_line mismatch: {report_line!r} vs {expected_report!r}')

    if latest_line not in news_text or report_line not in news_text:
        return _fail('/news must surface both dual-cache freshness lines')

    print('NEWS_FRESHNESS_DUAL_CACHE_LABEL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
