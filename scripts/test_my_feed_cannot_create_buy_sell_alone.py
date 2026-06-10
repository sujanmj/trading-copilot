#!/usr/bin/env python3
"""Unit tests — My Feed alone cannot create BUY/SELL (Stage 50A)."""

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
    print(f'MY_FEED_CANNOT_CREATE_BUY_SELL_ALONE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.my_feed_db import insert_feed_item
            from backend.analytics.unified_decision_engine import MY_FEED_MAX_SCORE, apply_my_feed_evidence

            insert_feed_item({
                'source': 'telegram_text',
                'raw_market_text': 'INFY strong buy breakout confirmed now today',
                'cleaned_summary': 'INFY strong buy breakout confirmed now today',
                'tickers': ['INFY'],
                'suggested_action': 'WATCH FOR CONFIRMATION',
                'impact_score': 95,
                'status': 'active',
            })
            ranked = [{
                'ticker': 'INFY',
                'action': 'AVOID',
                'score': 25,
                'why': [],
                'risk': [],
                'supports': [],
            }]
            updated = apply_my_feed_evidence(ranked, registry={})
            if updated[0].get('action') != 'AVOID':
                return _fail('My Feed must not override AVOID action alone')
            if int(updated[0].get('score') or 0) > MY_FEED_MAX_SCORE:
                return _fail('My Feed bump must stay below BUY threshold cap')

            ranked2 = [{
                'ticker': 'INFY',
                'action': 'WATCH_FOR_ENTRY',
                'score': 40,
                'why': [],
                'risk': [],
                'supports': [],
            }]
            out = apply_my_feed_evidence(ranked2, registry={})[0]
            if out.get('action') == 'BUY_CANDIDATE':
                return _fail('My Feed alone must not create BUY_CANDIDATE')
            if 'my_feed' in set(out.get('supports') or []):
                return _fail('my_feed must not count as independent BUY support')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MY_FEED_CANNOT_CREATE_BUY_SELL_ALONE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
