#!/usr/bin/env python3
"""Stage 50R — HCLTECH live merged catalyst output stays BULLISH / AI_INVESTMENT."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

GENERIC = 'Sensex rises over 250 points; HCL Tech among top gainers'
SPECIFIC = 'HCL Tech shares jump 3% after buying stake in Sarvam AI for Rs 1,427 crore'


def _fail(msg: str) -> int:
    print(f'HCLTECH_LIVE_MERGED_CLASSIFICATION_BULLISH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import (
        _merge_raw_by_ticker,
        score_catalyst_row,
    )

    merged = _merge_raw_by_ticker([
        {'ticker': 'HCLTECH', 'headline': GENERIC, 'published_at': '2026-06-16T10:00:00+05:30'},
        {'ticker': 'HCLTECH', 'headline': SPECIFIC, 'published_at': '2026-06-16T09:30:00+05:30'},
    ])
    if len(merged) != 1:
        return _fail(f'expected one merged row got {len(merged)}')
    row = merged[0]
    scored = score_catalyst_row(row)
    if scored.get('side') != 'BULLISH':
        return _fail(f'scored side must be BULLISH got {scored.get("side")!r}')
    if scored.get('catalyst_type') not in ('AI_INVESTMENT', 'STAKE_BUY'):
        return _fail(f'scored type must be AI/stake got {scored.get("catalyst_type")!r}')
    if SPECIFIC not in str(scored.get('headline') or ''):
        return _fail('specific Sarvam stake headline must be primary')
    if GENERIC not in (scored.get('catalyst_notes') or []):
        return _fail('generic Sensex headline must remain secondary note')

    payload = {
        'ok': True,
        'session_date': '2026-06-16',
        'items': [scored],
        'priority_list': [scored],
        'bullish_watch': [scored],
        'avoid_list': [],
    }
    explain_row = dict(scored)
    notes = explain_row.get('catalyst_notes') or []
    for note in notes:
        if note == GENERIC and 'Also:' not in str(explain_row):
            explain_row['secondary_headline'] = note
    side = str(explain_row.get('side') or '').upper()
    ctype = str(explain_row.get('catalyst_type') or '').upper()
    if side != 'BULLISH' or side == 'MIXED':
        return _fail(f'live merged row side must be BULLISH got {side!r}')
    if ctype not in ('AI_INVESTMENT', 'STAKE_BUY'):
        return _fail(f'live merged row type must be AI/stake got {ctype!r}')
    if payload['priority_list'][0].get('side') == 'MIXED':
        return _fail('priority_list must not downgrade HCLTECH to MIXED')

    print('HCLTECH_LIVE_MERGED_CLASSIFICATION_BULLISH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
