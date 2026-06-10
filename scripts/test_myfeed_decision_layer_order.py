#!/usr/bin/env python3
"""Stage 50G — My Feed decision layer order and catalyst-only role."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_DECISION_LAYER_ORDER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import (
        MYFEED_DECISION_LAYER_ORDER,
        MY_FEED_MAX_SCORE,
        apply_my_feed_evidence,
    )

    expected = (
        'market_mode_time_safety',
        'freshness',
        'scanner_price_volume',
        'watchlist_report_candidates',
        'news_govt_global_broker_myfeed_catalysts',
        'memory_calibration',
        'avoid_rejection_filters',
        'final_score',
        'watch_for_entry_avoid_wait',
    )
    if MYFEED_DECISION_LAYER_ORDER != expected:
        return _fail(f'decision layer order mismatch: {MYFEED_DECISION_LAYER_ORDER!r}')

    engine_src = (PROJECT_ROOT / 'backend/analytics/unified_decision_engine.py').read_text(encoding='utf-8')
    if 'Never creates BUY/SELL alone' not in engine_src:
        return _fail('apply_my_feed_evidence must document no blind BUY/SELL')

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.my_feed_db import insert_feed_item

            insert_feed_item({
                'source': 'telegram_text',
                'raw_market_text': 'INFY strong catalyst from user feed',
                'cleaned_summary': 'INFY strong catalyst from user feed',
                'tickers': ['INFY'],
                'suggested_action': 'WATCH FOR CONFIRMATION',
                'impact_score': 95,
                'status': 'active',
            })
            ranked = [{
                'ticker': 'INFY',
                'action': 'WATCH_FOR_ENTRY',
                'score': 40,
                'why': [],
                'risk': [],
                'supports': [],
            }]
            out = apply_my_feed_evidence(ranked, registry={'INFY': 'stale_data'})[0]
            if int(out.get('score') or 0) > MY_FEED_MAX_SCORE:
                return _fail('My Feed bump must stay capped below blind trade threshold')
            if str(out.get('action') or '').upper() in ('BUY', 'BUY_CANDIDATE', 'SELL', 'SELL_CANDIDATE'):
                return _fail('My Feed alone must not create BUY/SELL action')
            why = ' '.join(out.get('why') or [])
            if 'user_feed catalyst' not in why and 'live scanner rejected' not in why:
                return _fail('rejected ticker should note feed catalyst without overriding rejection')
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_DECISION_LAYER_ORDER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
