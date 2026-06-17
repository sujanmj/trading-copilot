#!/usr/bin/env python3
"""Stage 50T — bearish OFS catalyst stays AVOID/RISK without live quote."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CATALYST_AVOID_STATUS_WITHOUT_LIVE_QUOTE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import score_catalyst_row

    row = {
        'ticker': 'GICRE',
        'headline': 'GICRE OFS opens; promoter stake sale',
        'catalyst_type': 'OFS',
        'side': 'BEARISH',
        'catalyst_notes': ['GICRE OFS opens; promoter stake sale'],
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
        return _fail(f'GICRE OFS priority must be AVOID got {scored.get("priority")!r}')
    if scored.get('trade_status') != 'AVOID/RISK':
        return _fail(f'trade status must be AVOID/RISK got {scored.get("trade_status")!r}')
    if scored.get('trade_status') == 'WAIT FOR LIVE DATA':
        return _fail('bearish OFS must not use WAIT FOR LIVE DATA')
    if scored.get('price_display') != 'unavailable':
        return _fail('price may be unavailable but status must stay AVOID/RISK')

    print('CATALYST_AVOID_STATUS_WITHOUT_LIVE_QUOTE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
