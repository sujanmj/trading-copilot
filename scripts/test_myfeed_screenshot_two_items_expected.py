#!/usr/bin/env python3
"""Stage 50F — sample screenshot yields geopolitical + CHAMBLFERT items."""

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
    print(f'MYFEED_SCREENSHOT_TWO_ITEMS_EXPECTED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _vision_payload() -> dict:
    return {
        'ok': True,
        'confidence': 0.92,
        'ignored_private_items': 0,
        'items': [
            {
                'raw_market_text': 'Inshorts: Iran attacks US bases in Kuwait, Jordan, Bahrain',
                'cleaned_summary': 'Iran attacks US bases in Kuwait, Jordan, Bahrain',
                'detected_source_app': 'Inshorts',
                'tickers': [],
                'entities': ['IRAN', 'US', 'KUWAIT', 'JORDAN', 'BAHRAIN'],
                'themes': ['Geopolitical', 'Oil', 'Gold', 'Defence', 'Airlines'],
                'event_type': 'geopolitical',
                'sentiment': 'geopolitical',
                'impact_score': 80,
                'urgency': 'high',
                'suggested_action': 'MARKET RISK ALERT',
                'confirmation_required': False,
            },
            {
                'raw_market_text': 'INDmoney: CHAMBLFERT surges 5.3%',
                'cleaned_summary': 'CHAMBLFERT surges 5.3%',
                'detected_source_app': 'INDmoney',
                'tickers': ['CHAMBLFERT'],
                'entities': ['CHAMBLFERT'],
                'themes': [],
                'event_type': 'news',
                'sentiment': 'bullish',
                'impact_score': 72,
                'urgency': 'high',
                'suggested_action': 'WATCH FOR CONFIRMATION',
                'confirmation_required': True,
            },
        ],
    }


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.feed_processor import ingest_vision_items

            result = ingest_vision_items(_vision_payload()['items'], source='gui_screenshot')
        if not result.get('ok') or int(result.get('saved_count') or 0) != 2:
            return _fail(f'expected 2 saved items, got {result!r}')
        reply = str(result.get('reply') or '')
        if 'items_found=2' not in reply:
            return _fail('reply must include items_found=2')
        if 'MARKET RISK ALERT' not in reply:
            return _fail('geopolitical item must surface MARKET RISK ALERT')
        if 'CHAMBLFERT' not in reply:
            return _fail('reply must include CHAMBLFERT ticker/entity')
        if 'BUY' in reply or 'SELL' in reply:
            return _fail('My Feed must not emit BUY/SELL')

        records = result.get('records') or []
        actions = {str(r.get('suggested_action') or '') for r in records}
        if 'MARKET RISK ALERT' not in actions or 'WATCH FOR CONFIRMATION' not in actions:
            return _fail(f'expected both actions in records, got {actions!r}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_SCREENSHOT_TWO_ITEMS_EXPECTED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
