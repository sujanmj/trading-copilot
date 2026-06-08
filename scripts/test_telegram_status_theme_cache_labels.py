#!/usr/bin/env python3
"""Unit tests for Telegram /status theme cache label split (Stage 48H)."""

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
    print(f'TELEGRAM_STATUS_THEME_CACHE_LABELS_TEST_FAIL: {msg}', file=sys.stderr)
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
        _touch(data_root / 'daily_report_pack_latest.json', {'generated_at': now_iso, 'summary': {}})
        _touch(data_root / 'scanner_data.json', {'generated_at': now_iso})
        _touch(data_root / 'news_feed.json', {'updated_at': now_iso})
        _touch(data_root / 'budget_impact_cache.json', {
            'ok': True,
            'generated_at': now_iso,
            'themes_by_id': {},
        })

        import backend.storage.data_paths as dp
        import backend.telegram.lazy_command_runner as lcr

        orig_root = dp.get_data_root
        orig_pack = lcr.DAILY_PACK_FILE
        dp.get_data_root = lambda: data_root  # type: ignore[method-assign]
        lcr.DAILY_PACK_FILE = data_root / 'daily_report_pack_latest.json'

        try:
            text_no_legacy = format_status_text()
        finally:
            dp.get_data_root = orig_root  # type: ignore[method-assign]
            lcr.DAILY_PACK_FILE = orig_pack

    required = (
        'Latest budget cache:',
        'Latest budget theme cache:',
        'Telegram build: <code>AstraEdge 48H</code>',
    )
    for label in required:
        if label not in text_no_legacy:
            return _fail(f'missing {label!r}')

    if 'Latest theme cache:' in text_no_legacy:
        return _fail('must not label budget theme cache as Latest theme cache')
    if 'Legacy theme cache:' in text_no_legacy:
        return _fail('Legacy theme cache should be hidden when theme_baskets missing')

    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / 'data'
        data_root.mkdir()
        _touch(data_root / 'daily_report_pack_latest.json', {'generated_at': now_iso, 'summary': {}})
        _touch(data_root / 'scanner_data.json', {'generated_at': now_iso})
        _touch(data_root / 'news_feed.json', {'updated_at': now_iso})
        _touch(data_root / 'budget_impact_cache.json', {'ok': True, 'generated_at': now_iso})
        _touch(data_root / 'theme_baskets.json', {'cache_refreshed_at': '2026-06-01T10:00:00+05:30'})

        import backend.storage.data_paths as dp
        import backend.telegram.lazy_command_runner as lcr

        orig_root = dp.get_data_root
        orig_pack = lcr.DAILY_PACK_FILE
        dp.get_data_root = lambda: data_root  # type: ignore[method-assign]
        lcr.DAILY_PACK_FILE = data_root / 'daily_report_pack_latest.json'

        try:
            text_with_legacy = format_status_text()
        finally:
            dp.get_data_root = orig_root  # type: ignore[method-assign]
            lcr.DAILY_PACK_FILE = orig_pack

    if 'Legacy theme cache:' not in text_with_legacy:
        return _fail('Legacy theme cache label expected when theme_baskets exists')

    print('TELEGRAM_STATUS_THEME_CACHE_LABELS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
