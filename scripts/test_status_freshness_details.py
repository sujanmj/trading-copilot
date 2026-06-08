#!/usr/bin/env python3
"""Unit tests for /status freshness detail lines (Stage 47E)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'STATUS_FRESHNESS_DETAILS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _touch(path: Path, payload: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        path.write_text(json.dumps(payload), encoding='utf-8')
    else:
        path.write_text('{}', encoding='utf-8')


def main() -> int:
    from backend.telegram.response_format import format_status_text

    ist = ZoneInfo('Asia/Kolkata')
    now_iso = datetime.now(ist).replace(microsecond=0).isoformat()

    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / 'data'
        data_root.mkdir()
        pack = {
            'generated_at': now_iso,
            'summary': {'market_mode': 'INDIA_MARKET_HOURS'},
        }
        _touch(data_root / 'daily_report_pack_latest.json', pack)
        _touch(data_root / 'scanner_data.json', {'generated_at': now_iso, 'session_date': '2026-06-08'})
        _touch(data_root / 'news_feed.json', {'updated_at': now_iso, 'articles': []})
        _touch(
            data_root / 'theme_baskets.json',
            {'cache_refreshed_at': now_iso, 'baskets': [], 'stage': '47F', 'theme_schema_version': '47F'},
        )

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

    if 'AstraEdge 48C' not in text:
        return _fail('status missing AstraEdge 48C build line')
    for label in (
        'Latest report:',
        'Latest scanner:',
        'Latest news:',
        'Latest theme cache:',
        'Market mode:',
    ):
        if label not in text:
            return _fail(f'status missing {label!r}')
    if 'fresh' not in text.lower() and 'stale' not in text.lower():
        return _fail('status should include fresh|stale labels')

    print('STATUS_FRESHNESS_DETAILS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
