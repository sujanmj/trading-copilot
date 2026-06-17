#!/usr/bin/env python3
"""Stage 50X — /feed always returns an immediate Telegram reply."""

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
    print(f'MYFEED_FEED_ALWAYS_REPLIES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.feed_processor import ingest_text
    from backend.telegram.lazy_command_runner import run_feed_text_only

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=[]):
            empty = ingest_text('', source='telegram_text')
            unverified = ingest_text('adani lost airport contract to kenya', source='telegram_text')
            runner = run_feed_text_only('adani lost airport contract to kenya')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for label, reply in (('empty', empty.get('reply')), ('unverified', unverified.get('reply')), ('runner', runner.get('text'))):
        text = str(reply or '')
        if not text.strip():
            return _fail(f'{label} must not be silent')
        if label == 'empty' and 'MY_FEED_NEEDS_TEXT' not in text:
            return _fail('empty feed must ask for text')
        if label in ('unverified', 'runner') and 'MY_FEED_SAVED' not in text and 'MY_FEED_SAVE_FAILED' not in text:
            return _fail(f'{label} must include save marker')
        if label in ('unverified', 'runner') and 'Feed ID:' not in text:
            return _fail(f'{label} must include Feed ID line')

    if '⚠️ Feed saved as UNVERIFIED' not in str(unverified.get('reply') or ''):
        return _fail('unverified adani feed must show UNVERIFIED reply')

    print('MYFEED_FEED_ALWAYS_REPLIES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
