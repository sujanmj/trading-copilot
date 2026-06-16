#!/usr/bin/env python3
"""Stage 50S — live /catalysts explain path keeps HCLTECH BULLISH AI_INVESTMENT."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

GENERIC = 'Sensex rises over 250 points; HCL Tech among top gainers'
SPECIFIC = 'HCL Tech shares jump 3% after buying stake in Sarvam AI for Rs 1,427 crore'


def _fail(msg: str) -> int:
    print(f'HCLTECH_LIVE_CATALYST_PATH_BULLISH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import (
        build_catalyst_radar,
        format_catalyst_radar_telegram,
        score_catalyst_row,
        _merge_raw_by_ticker,
    )

    merged = _merge_raw_by_ticker([
        {'ticker': 'HCLTECH', 'headline': GENERIC, 'published_at': '2026-06-16T10:00:00+05:30', 'source_key': 'news_feed'},
        {'ticker': 'HCLTECH', 'headline': SPECIFIC, 'published_at': '2026-06-16T09:30:00+05:30', 'source_key': 'news_feed'},
    ])
    row = merged[0]
    if GENERIC not in (row.get('catalyst_notes') or []):
        row = {**row, 'catalyst_notes': [SPECIFIC, GENERIC]}
    scored = score_catalyst_row(row)
    radar = {
        'ok': True,
        'session_date': '2099-01-01',
        'items': [scored],
        'priority_list': [scored],
        'bullish_watch': [scored],
        'avoid_list': [],
    }

    with patch('backend.intelligence.stock_catalyst_radar._collect_raw_catalysts', return_value=[
        {'ticker': 'HCLTECH', 'headline': GENERIC, 'published_at': '2026-06-16T10:00:00+05:30', 'source_key': 'news_feed', 'catalyst_type': 'GENERAL_NEWS', 'side': 'BULLISH'},
        {'ticker': 'HCLTECH', 'headline': SPECIFIC, 'published_at': '2026-06-16T09:30:00+05:30', 'source_key': 'news_feed', 'catalyst_type': 'AI_INVESTMENT', 'side': 'BULLISH'},
    ]), patch('backend.intelligence.stock_catalyst_radar._today', return_value='2099-01-01'), \
         patch('backend.intelligence.stock_catalyst_radar.CACHE_FILE', PROJECT_ROOT / 'data' / '_test_catalyst_cache.json'), \
         patch('backend.intelligence.stock_catalyst_radar.get_catalyst_radar', return_value=radar):
        built = build_catalyst_radar(force_refresh=True, persist=False)
        explain_text = format_catalyst_radar_telegram(explain_ticker='HCLTECH')

    if scored.get('side') != 'BULLISH':
        return _fail(f'scored side must be BULLISH got {scored.get("side")!r}')
    if scored.get('catalyst_type') not in ('AI_INVESTMENT', 'STAKE_BUY'):
        return _fail(f'scored type must be AI/stake got {scored.get("catalyst_type")!r}')
    if SPECIFIC not in str(scored.get('headline') or ''):
        return _fail('Sarvam stake headline must be primary')
    if 'Side: MIXED' in explain_text:
        return _fail('live explain path must not show MIXED for HCLTECH Sarvam stake')
    if 'Side: BULLISH' not in explain_text:
        return _fail('live explain path must show BULLISH')
    if 'AI INVESTMENT' not in explain_text.upper() and 'STAKE BUY' not in explain_text.upper():
        return _fail('live explain path must show AI investment / stake buy type')
    if GENERIC not in explain_text:
        return _fail('generic Sensex headline must remain in Also section')
    if built.get('priority_list') and built['priority_list'][0].get('side') == 'MIXED':
        return _fail('built priority_list must not downgrade HCLTECH to MIXED')

    print('HCLTECH_LIVE_CATALYST_PATH_BULLISH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
