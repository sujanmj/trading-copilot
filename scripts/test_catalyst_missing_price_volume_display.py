#!/usr/bin/env python3
"""Stage 50O — missing quote shows unavailable not 0.0."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CATALYST_MISSING_PRICE_VOLUME_DISPLAY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import score_catalyst_row

    row = {
        'ticker': 'HCLTECH',
        'catalyst_type': 'AI_INVESTMENT',
        'side': 'BULLISH',
        'source_key': 'news_feed',
        'published_at': '2026-06-16T09:00:00+05:30',
    }
    with patch('backend.intelligence.stock_catalyst_radar._scanner_quote', return_value={}):
        scored = score_catalyst_row(row)

    if scored.get('price_display') != 'unavailable':
        return _fail(f"price_display must be unavailable got {scored.get('price_display')!r}")
    if scored.get('volume_display') != 'unavailable':
        return _fail(f"volume_display must be unavailable got {scored.get('volume_display')!r}")
    if scored.get('trade_status') != 'WAIT FOR LIVE DATA':
        return _fail(f"expected WAIT FOR LIVE DATA got {scored.get('trade_status')!r}")
    if scored.get('change_pct') == 0.0 and scored.get('quote_available') is False:
        pass
    elif scored.get('change_pct') == 0:
        return _fail('must not fake 0.0 change when quote unavailable')

    print('CATALYST_MISSING_PRICE_VOLUME_DISPLAY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
