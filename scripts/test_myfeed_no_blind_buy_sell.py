#!/usr/bin/env python3
"""Unit tests — My Feed never blind BUY/SELL (Stage 50B)."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BLIND_ACTIONS = frozenset({'BUY', 'SELL', 'BUY_CANDIDATE', 'SELL_CANDIDATE', 'STRONG BUY', 'STRONG SELL'})


def _fail(msg: str) -> int:
    print(f'MYFEED_NO_BLIND_BUY_SELL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.feed_processor import _classify_item, ingest_text

    aggressive = _classify_item({
        'cleaned_summary': 'INFY strong buy breakout confirmed now today sell HDFC immediately',
        'items_found': 2,
        'tickers': ['INFY', 'HDFC'],
    })
    action = str(aggressive.get('suggested_action') or '').upper()
    if action in BLIND_ACTIONS or 'BUY' in action or 'SELL' in action:
        return _fail(f'_classify_item must not emit BUY/SELL, got {action!r}')

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.analytics.unified_decision_engine import MY_FEED_MAX_SCORE, apply_my_feed_evidence
            from backend.my_feed.my_feed_db import insert_feed_item

            for text in (
                'TCS strong buy now breakout confirmed',
                'RELIANCE sell immediately on downgrade risk',
            ):
                result = ingest_text(text, source='telegram_text')
                if not result.get('ok'):
                    continue
                stored_action = str((result.get('record') or {}).get('suggested_action') or '').upper()
                if stored_action in BLIND_ACTIONS or 'BUY' in stored_action or 'SELL' in stored_action:
                    return _fail(f'ingest suggested_action must not be BUY/SELL, got {stored_action!r}')

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
            out_action = str(updated[0].get('action') or '').upper()
            if out_action in BLIND_ACTIONS or out_action == 'BUY_CANDIDATE':
                return _fail('decision engine must not create BUY/SELL from feed alone')
            if int(updated[0].get('score') or 0) > MY_FEED_MAX_SCORE:
                return _fail('My Feed score bump must stay below blind BUY threshold')

            ranked2 = [{
                'ticker': 'INFY',
                'action': 'WATCH_FOR_ENTRY',
                'score': 40,
                'why': [],
                'risk': [],
                'supports': [],
            }]
            out2 = apply_my_feed_evidence(ranked2, registry={})[0]
            if str(out2.get('action') or '').upper() == 'BUY_CANDIDATE':
                return _fail('My Feed alone must not promote to BUY_CANDIDATE')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    processor_src = (PROJECT_ROOT / 'backend/my_feed/feed_processor.py').read_text(encoding='utf-8')
    if "'BUY'" in processor_src or "'SELL'" in processor_src:
        return _fail('feed_processor must not define BUY/SELL suggested_action literals')

    print('MYFEED_NO_BLIND_BUY_SELL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
