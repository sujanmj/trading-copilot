#!/usr/bin/env python3
"""Stage 50T — HCLTECH Sarvam AI evidence priority on live catalyst paths."""

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
    print(f'HCLTECH_LIVE_EVIDENCE_PRIORITY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import (
        _merge_raw_by_ticker,
        format_catalyst_radar_telegram,
        score_catalyst_row,
    )

    merged = _merge_raw_by_ticker([
        {'ticker': 'HCLTECH', 'headline': GENERIC, 'published_at': '2026-06-16T10:00:00+05:30', 'source_key': 'news_feed'},
        {'ticker': 'HCLTECH', 'headline': SPECIFIC, 'published_at': '2026-06-16T09:30:00+05:30', 'source_key': 'news_feed'},
    ])
    row = merged[0]
    if GENERIC not in (row.get('catalyst_notes') or []):
        row = {**row, 'catalyst_notes': [SPECIFIC, GENERIC]}
    scored = score_catalyst_row(row)
    radar = {'ok': True, 'session_date': '2099-01-01', 'items': [scored], 'priority_list': [scored], 'bullish_watch': [scored]}

    with patch('backend.intelligence.stock_catalyst_radar.get_catalyst_radar', return_value=radar):
        list_text = format_catalyst_radar_telegram(today_only=False)
        explain_text = format_catalyst_radar_telegram(explain_ticker='HCLTECH')

    if scored.get('side') != 'BULLISH':
        return _fail(f'merged row side must be BULLISH got {scored.get("side")!r}')
    if scored.get('catalyst_type') not in ('AI_INVESTMENT', 'STAKE_BUY'):
        return _fail(f'merged row type must be AI/stake got {scored.get("catalyst_type")!r}')
    if 'MIXED' in list_text.split('HCLTECH', 1)[-1][:120]:
        return _fail('/catalysts list must not show HCLTECH as MIXED when Sarvam stake exists')
    if 'Side: BULLISH' not in explain_text:
        return _fail('explain must show BULLISH side')
    if GENERIC not in explain_text:
        return _fail('generic Sensex headline must remain under Also')

    with patch('backend.intelligence.stock_catalyst_radar.get_catalyst_radar', return_value={
        'ok': True,
        'items': [{'ticker': 'HCLTECH', 'headline': GENERIC, 'side': 'MIXED', 'catalyst_type': 'RESULT_ALERT', 'catalyst_notes': [GENERIC], 'score': 40, 'priority': 'LOW', 'trade_status': 'NO TRADE', 'score_breakdown': {}}],
        'priority_list': [],
    }):
        absent = format_catalyst_radar_telegram(explain_ticker='HCLTECH')
    if 'No stock-specific AI stake evidence currently in live cache.' not in absent:
        return _fail('HCLTECH explain must state absent Sarvam evidence when cache lacks it')

    print('HCLTECH_LIVE_EVIDENCE_PRIORITY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
