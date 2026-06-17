#!/usr/bin/env python3
"""Stage 50X — /myfeed scan unverified count matches active unverified rows."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_SCAN_COUNTS_UNVERIFIED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.feed_processor import ingest_text, scan_feed_summary
    from backend.my_feed.telegram_handlers import format_myfeed_scan

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=[]):
            ingest_text('adani lost airport contract to kenya', source='telegram_text')
            ingest_text('random unverified claim about infra sector', source='telegram_text')
            summary = scan_feed_summary(today_only=False)
            text = format_myfeed_scan(summary)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    unverified = int(summary.get('unverified') or 0)
    if unverified < 2:
        return _fail(f'expected at least 2 unverified active rows, got {unverified}')
    if f'Unverified active: {unverified}' not in text:
        return _fail('scan text must show Unverified active count')
    if 'Unverified: 0' in text:
        return _fail('scan must not report Unverified: 0 when rows exist')

    print('MYFEED_SCAN_COUNTS_UNVERIFIED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
