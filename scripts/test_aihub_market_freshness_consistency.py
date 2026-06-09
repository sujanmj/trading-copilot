#!/usr/bin/env python3
"""Unit tests — unified market freshness across /aihub market (Stage 48R)."""

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
    print(f'AIHUB_MARKET_FRESHNESS_CONSISTENCY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _touch(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


def main() -> int:
    from backend.telegram.freshness_consistency import get_unified_market_freshness
    from backend.telegram.response_format import format_aihub_market_section, format_aihub_payload

    ist = ZoneInfo('Asia/Kolkata')
    fresh_iso = (datetime.now(ist) - timedelta(minutes=3)).replace(microsecond=0).isoformat()

    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / 'data'
        data_root.mkdir()
        _touch(data_root / 'scanner_data.json', {'generated_at': fresh_iso, 'top_signals': []})
        _touch(data_root / 'daily_report_pack_latest.json', {'generated_at': fresh_iso, 'summary': {}})
        _touch(data_root / 'runtime_snapshot.json', {'generated_at': fresh_iso})

        import backend.storage.data_paths as dp
        import backend.telegram.lazy_command_runner as lcr

        orig_root = dp.get_data_root
        orig_pack = lcr.DAILY_PACK_FILE
        dp.get_data_root = lambda: data_root  # type: ignore[method-assign]
        lcr.DAILY_PACK_FILE = data_root / 'daily_report_pack_latest.json'

        try:
            unified = get_unified_market_freshness()
            market_payload = {
                'source': 'cache',
                'cache_age_seconds': 180,
                'summary': {'market_mode': 'intraday'},
                'items': [],
                'warnings': [],
            }
            section_lines = format_aihub_market_section(market_payload)
            aihub_text = format_aihub_payload('market', market_payload)
        finally:
            dp.get_data_root = orig_root  # type: ignore[method-assign]
            lcr.DAILY_PACK_FILE = orig_pack

    market_line = unified.get('line', '')
    if not market_line.startswith('Market:'):
        return _fail(f'unified market line must start with Market: got {market_line!r}')
    if not unified.get('is_fresh'):
        return _fail(f'scanner at 3m should be fresh: {unified!r}')
    if unified.get('reason') != 'scanner-aligned':
        return _fail(f'expected scanner-aligned reason got {unified.get("reason")!r}')

    if not section_lines or section_lines[0] != market_line:
        return _fail('format_aihub_market_section must lead with unified market line')
    if market_line not in aihub_text:
        return _fail('format_aihub_payload market must include unified market line')

    print('AIHUB_MARKET_FRESHNESS_CONSISTENCY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
