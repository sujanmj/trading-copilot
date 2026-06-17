#!/usr/bin/env python3
"""Stage 50U — bearish/risk catalyst rows always show AVOID/RISK trade status."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CATALYST_AVOID_TRADE_STATUS_OVERRIDE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import (
        _finalize_catalyst_display_row,
        format_catalyst_radar_telegram,
        score_catalyst_row,
    )

    for ticker, side, ctype, headline in (
        ('GICRE', 'BEARISH', 'OFS', 'GICRE OFS opens; promoter stake sale'),
        ('SUZLON', 'RISK', 'GENERAL_NEWS', 'SUZLON falls 8% on weak order book'),
    ):
        row = {
            'ticker': ticker,
            'headline': headline,
            'catalyst_type': ctype,
            'side': side,
            'catalyst_notes': [headline],
            'published_at': '2026-06-16T10:00:00+05:30',
            'source_key': 'news_feed',
        }
        with patch('backend.intelligence.stock_catalyst_radar._scanner_quote', return_value=None), \
             patch('backend.intelligence.stock_catalyst_radar._quote_metrics', return_value={
                 'change_pct': None,
                 'volume_ratio': None,
                 'quote_available': False,
             }):
            scored = score_catalyst_row(row)
        if scored.get('priority') != 'AVOID':
            return _fail(f'{ticker} priority must be AVOID got {scored.get("priority")!r}')
        if scored.get('trade_status') != 'AVOID/RISK':
            return _fail(f'{ticker} trade status must be AVOID/RISK got {scored.get("trade_status")!r}')

    stale = {
        'ticker': 'GICRE',
        'side': 'BEARISH',
        'priority': 'AVOID',
        'trade_status': 'WAIT FOR LIVE DATA',
        'catalyst_type': 'OFS',
        'headline': 'GICRE OFS',
        'price_display': 'unavailable',
        'volume_display': 'unavailable',
        'score': 20,
        'score_breakdown': {},
        'freshness_label': 'today',
    }
    fixed = _finalize_catalyst_display_row(stale)
    radar = {'ok': True, 'items': [fixed], 'priority_list': [fixed], 'bullish_watch': []}
    with patch('backend.intelligence.stock_catalyst_radar.get_catalyst_radar', return_value=radar):
        text = format_catalyst_radar_telegram(today_only=False)
    if 'WAIT FOR LIVE DATA' in text.split('GICRE', 1)[-1][:200]:
        return _fail('/catalysts list must not show WAIT FOR LIVE DATA for GICRE AVOID row')
    if 'AVOID/RISK' not in text:
        return _fail('/catalysts list must show AVOID/RISK')

    print('CATALYST_AVOID_TRADE_STATUS_OVERRIDE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
