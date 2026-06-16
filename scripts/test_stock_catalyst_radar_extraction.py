#!/usr/bin/env python3
"""Stage 50N — catalyst radar extracts and ranks news items."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'STOCK_CATALYST_RADAR_EXTRACTION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import _collect_raw_catalysts, build_catalyst_radar

    fake_news = {
        'items': [
            {'title': 'HCL Technologies picks stake in Sarvam AI startup', 'published': '2026-06-16T08:00:00+05:30'},
            {'title': 'Arvind SmartSpaces announces new housing project in Pune', 'published': '2026-06-16T07:30:00+05:30'},
        ],
    }
    with patch('backend.intelligence.stock_catalyst_radar._load_json', side_effect=lambda p: fake_news if 'news_feed' in str(p) else {}), \
         patch('backend.intelligence.stock_catalyst_radar._iter_external_evidence', return_value=[]), \
         patch('backend.intelligence.stock_catalyst_radar._iter_inshorts', return_value=[]), \
         patch('backend.intelligence.stock_catalyst_radar._iter_nse_filings', return_value=[]), \
         patch('backend.intelligence.stock_catalyst_radar._iter_my_feed_text', return_value=[]), \
         patch('backend.intelligence.stock_catalyst_radar.CACHE_FILE', PROJECT_ROOT / 'data' / '_test_catalyst_radar.json'):
        raw = _collect_raw_catalysts()
        radar = build_catalyst_radar(persist=False, force_refresh=True)

    tickers = {r.get('ticker') for r in raw}
    if 'HCLTECH' not in tickers and 'ARVSMART' not in tickers:
        return _fail(f'expected HCLTECH/ARVSMART in raw catalysts got {tickers}')
    if not radar.get('priority_list'):
        return _fail('priority_list must not be empty')
    if radar.get('stage') != '50N':
        return _fail('radar stage must be 50N')

    print('STOCK_CATALYST_RADAR_EXTRACTION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
