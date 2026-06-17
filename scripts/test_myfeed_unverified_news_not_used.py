#!/usr/bin/env python3
"""Stage 50W — unverified My Feed items are not catalyst-eligible."""

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
    print(f'MYFEED_UNVERIFIED_NEWS_NOT_USED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import apply_my_feed_evidence
    from backend.intelligence.stock_catalyst_radar import _iter_my_feed_text
    from backend.my_feed.feed_processor import ingest_text
    from backend.my_feed.feed_verification import VERIFICATION_UNVERIFIED

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path), \
             patch('backend.my_feed.feed_verification.iter_verification_source_articles', return_value=[]):
            result = ingest_text('OBSCUREXYZ wins secret contract nobody reported', source='telegram_text')
            if not result.get('ok'):
                return _fail('unverified ingest must still save')
            reply = str(result.get('reply') or '')
            if VERIFICATION_UNVERIFIED not in reply:
                return _fail(f'reply must show UNVERIFIED, got {reply!r}')
            if 'Used as catalyst evidence: no' not in reply:
                return _fail('reply must state Used as catalyst evidence: no')
            if 'Not used for catalyst/tradecard boost until verified.' not in reply:
                return _fail('reply must warn unverified catalyst exclusion')

            record = result.get('record') or {}
            if str(record.get('verification_status') or '').upper() != VERIFICATION_UNVERIFIED:
                return _fail('stored verification_status must be UNVERIFIED')
            if str(record.get('catalyst_eligible')).lower() in ('true', '1'):
                return _fail('unverified feed must not be catalyst_eligible=true')

            myfeed_rows = _iter_my_feed_text()
            if myfeed_rows:
                return _fail('unverified feed must not appear in catalyst my_feed iterator')

            ranked = [{
                'ticker': 'OBSCUREXYZ',
                'action': 'WATCH_FOR_ENTRY',
                'score': 40,
                'why': [],
                'risk': [],
                'supports': [],
            }]
            out = apply_my_feed_evidence(ranked, registry={})[0]
            if int(out.get('score') or 0) != 40:
                return _fail('unverified feed must not bump decision score')
            why = ' '.join(out.get('why') or [])
            if 'user_feed catalyst' in why:
                return _fail('unverified feed must not add catalyst note')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_UNVERIFIED_NEWS_NOT_USED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
