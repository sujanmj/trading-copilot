#!/usr/bin/env python3
"""
Verify historical import uses timezone.utc (Python 3.11 compatible).

Usage:
  python scripts/test_historical_import_utc_compat.py

Prints exactly HISTORICAL_IMPORT_UTC_COMPAT_OK on success; exits 1 on failure.
"""

from __future__ import annotations

import sys
from datetime import timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os
    os.chdir(PROJECT_ROOT)

SCRIPTS_DIR = PROJECT_ROOT / 'scripts'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

IMPORT_SCRIPT = SCRIPTS_DIR / 'import_historical_prices.py'


def _fail(msg: str) -> int:
    print(f'HISTORICAL_IMPORT_UTC_COMPAT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    source = IMPORT_SCRIPT.read_text(encoding='utf-8')
    if 'datetime.UTC' in source:
        return _fail('datetime.UTC found in import_historical_prices.py')
    if 'timezone.utc' not in source:
        return _fail('timezone.utc missing in import_historical_prices.py')

    import import_historical_prices as ihp

    # 2026-05-15 00:00:00 UTC
    mock_ts = 1778803200
    date_str = ihp._timestamp_utc_date(mock_ts)
    if not date_str or len(date_str) != 10 or date_str[4] != '-' or date_str[7] != '-':
        return _fail(f'unexpected date format from _timestamp_utc_date: {date_str!r}')

    # Ensure helper uses timezone.utc, not datetime.UTC
    from datetime import datetime
    expected = datetime.fromtimestamp(mock_ts, timezone.utc).strftime('%Y-%m-%d')
    if date_str != expected:
        return _fail(f'timestamp mismatch: got {date_str!r}, expected {expected!r}')

    # Mock Yahoo chart block parsing via helper path
    parsed = ihp._timestamp_utc_date(1777593600)
    if parsed != '2026-05-01':
        return _fail(f'yahoo-style timestamp parse failed: {parsed!r}')

    print('HISTORICAL_IMPORT_UTC_COMPAT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
