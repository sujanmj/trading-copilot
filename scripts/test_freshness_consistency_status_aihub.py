#!/usr/bin/env python3
"""Unit tests — /status scanner freshness matches /aihub scan format (Stage 48Q)."""

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
    print(f'FRESHNESS_CONSISTENCY_STATUS_AIHUB_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _touch(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


def main() -> int:
    from backend.telegram.freshness_consistency import format_compact_freshness_line
    from backend.telegram.response_format import format_aihub_payload, format_status_text

    ist = ZoneInfo('Asia/Kolkata')
    fresh_iso = (datetime.now(ist) - timedelta(minutes=2)).replace(microsecond=0).isoformat()

    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / 'data'
        data_root.mkdir()
        _touch(data_root / 'daily_report_pack_latest.json', {'generated_at': fresh_iso, 'summary': {}})
        _touch(data_root / 'scanner_data.json', {'generated_at': fresh_iso, 'top_signals': []})
        _touch(data_root / 'news_feed.json', {'updated_at': fresh_iso, 'articles': []})
        _touch(data_root / 'budget_impact_cache.json', {
            'ok': True,
            'generated_at': fresh_iso,
            'stage': '48Q',
        })

        import backend.storage.data_paths as dp
        import backend.telegram.lazy_command_runner as lcr

        orig_root = dp.get_data_root
        orig_pack = lcr.DAILY_PACK_FILE
        dp.get_data_root = lambda: data_root  # type: ignore[method-assign]
        lcr.DAILY_PACK_FILE = data_root / 'daily_report_pack_latest.json'

        try:
            status_text = format_status_text()
            scan_payload = {
                'source': 'cache',
                'cache_age_seconds': 120,
                'summary': {'live_scanner_count': 4, 'watchlist_count': 2, 'memory_signal_count': 1},
                'items': [],
            }
            aihub_text = format_aihub_payload('scan', scan_payload)
        finally:
            dp.get_data_root = orig_root  # type: ignore[method-assign]
            lcr.DAILY_PACK_FILE = orig_pack

    status_scanner = next(
        (ln for ln in status_text.splitlines() if ln.lower().startswith('scanner:')),
        '',
    )
    aihub_scanner = next(
        (ln for ln in aihub_text.splitlines() if ln.startswith('Scanner:')),
        '',
    )
    if not status_scanner:
        return _fail(f'status missing scanner freshness line: {status_text!r}')
    if not aihub_scanner:
        return _fail(f'aihub scan missing scanner freshness line: {aihub_text!r}')

    for line in (status_scanner, aihub_scanner):
        if 'fresh' not in line.lower():
            return _fail(f'scanner should be fresh at 2m: {line!r}')
        if '2m' not in line:
            return _fail(f'scanner age should show 2m: {line!r}')

    expected = format_compact_freshness_line('Scanner', 2)
    if aihub_scanner != expected:
        return _fail(f'aihub scan line must use compact format {expected!r} got {aihub_scanner!r}')

    status_parts = status_scanner.split(':', 1)[1].strip()
    aihub_parts = aihub_scanner.split(':', 1)[1].strip()
    if status_parts != aihub_parts:
        return _fail(f'status/aihub scanner suffix mismatch: {status_parts!r} vs {aihub_parts!r}')

    print('FRESHNESS_CONSISTENCY_STATUS_AIHUB_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
