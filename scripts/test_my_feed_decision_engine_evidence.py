#!/usr/bin/env python3
"""Unit tests — My Feed evidence integration (Stage 50A)."""

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
    print(f'MY_FEED_DECISION_ENGINE_EVIDENCE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.my_feed_db import insert_feed_item
            from backend.analytics.unified_decision_engine import apply_my_feed_evidence

            insert_feed_item({
                'source': 'telegram_text',
                'raw_market_text': 'TATASTEEL breakout watch on volume today',
                'cleaned_summary': 'TATASTEEL breakout watch on volume today',
                'tickers': ['TATASTEEL'],
                'suggested_action': 'WATCH FOR CONFIRMATION',
                'impact_score': 72,
                'urgency': 'high',
                'status': 'active',
            })
            ranked = [{
                'ticker': 'TATASTEEL',
                'action': 'WATCH_FOR_ENTRY',
                'score': 48,
                'why': [],
                'risk': [],
                'supports': ['scanner'],
            }]
            updated = apply_my_feed_evidence(ranked, registry={})
            row = updated[0]
            why_blob = ' '.join(row.get('why') or [])
            if 'My Feed catalyst' not in why_blob:
                return _fail('expected My Feed catalyst note in why')
            if int(row.get('score') or 0) <= 48:
                return _fail('expected small score bump from My Feed evidence')
            if 'my_feed' not in (row.get('evidence_notes') or []):
                return _fail('expected evidence_notes to include my_feed')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MY_FEED_DECISION_ENGINE_EVIDENCE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
