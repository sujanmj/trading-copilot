#!/usr/bin/env python3
"""Stage 50O — priority AVOID must align with trade status."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CATALYST_PRIORITY_STATUS_CONSISTENCY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import score_catalyst_row

    row = {
        'ticker': 'GICRE',
        'catalyst_type': 'OFS',
        'side': 'BEARISH',
        'source_key': 'news_feed',
        'published_at': '2026-06-16T09:00:00+05:30',
    }
    with patch('backend.intelligence.stock_catalyst_radar._scanner_quote', return_value={
        'ticker': 'GICRE', 'price': 400, 'change_percent': -6, 'volume_ratio': 0.5,
    }):
        scored = score_catalyst_row(row)

    if scored.get('priority') != 'AVOID':
        return _fail(f'expected AVOID priority got {scored.get("priority")}')
    if scored.get('trade_status') != 'AVOID/RISK':
        return _fail(f'AVOID priority must not have WAIT FOR VOLUME, got {scored.get("trade_status")!r}')

    print('CATALYST_PRIORITY_STATUS_CONSISTENCY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
