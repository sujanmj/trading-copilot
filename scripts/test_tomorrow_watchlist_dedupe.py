#!/usr/bin/env python3
"""
Test tomorrow watchlist ticker deduplication.

Prints exactly TOMORROW_WATCHLIST_DEDUPE_TEST_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TOMORROW_WATCHLIST_DEDUPE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.tomorrow_watchlist_report import (
        dedupe_candidates_by_ticker,
        explain_watch_candidate,
        group_by_decision,
    )

    rows = [
        {
            'ticker': 'RELIANCE',
            'prediction_id': 'mm:low',
            'final_score': 40,
            'decision': 'WATCH',
            'hard_warnings': [],
            'warnings': [],
            'explanations': ['A: lower score => +0'],
        },
        {
            'ticker': 'RELIANCE',
            'prediction_id': 'mm:high',
            'final_score': 55,
            'decision': 'WATCH',
            'timestamp': '2026-05-31T12:00:00+00:00',
            'hard_warnings': [],
            'warnings': [],
            'explanations': ['A: higher score => +5'],
        },
        {
            'ticker': 'TCS',
            'prediction_id': 'mm:tcs',
            'final_score': 48,
            'decision': 'WATCH',
            'hard_warnings': [],
            'warnings': [],
            'explanations': [],
        },
    ]

    deduped, stats = dedupe_candidates_by_ticker(rows)
    if stats['raw_candidates'] != 3:
        return _fail(f'expected raw_candidates=3, got {stats["raw_candidates"]}')
    if stats['unique_tickers'] != 2:
        return _fail(f'expected unique_tickers=2, got {stats["unique_tickers"]}')
    if stats['duplicates_removed'] != 1:
        return _fail(f'expected duplicates_removed=1, got {stats["duplicates_removed"]}')

    reliance_rows = [row for row in deduped if row.get('ticker') == 'RELIANCE']
    if len(reliance_rows) != 1:
        return _fail('RELIANCE should appear once after dedupe')

    winner = reliance_rows[0]
    if winner.get('prediction_id') != 'mm:high':
        return _fail('higher score candidate should be retained')
    if winner.get('grouped_candidate_count') != 2:
        return _fail('grouped_candidate_count should be 2')
    if set(winner.get('grouped_prediction_ids') or []) != {'mm:low', 'mm:high'}:
        return _fail('grouped_prediction_ids missing duplicate evidence')
    if sorted(winner.get('grouped_scores') or []) != [40, 55]:
        return _fail(f'unexpected grouped_scores: {winner.get("grouped_scores")}')

    grouped = group_by_decision(deduped)
    watch = grouped['WATCH']
    tickers = [item.get('ticker') for item in watch]
    if tickers.count('RELIANCE') != 1:
        return _fail('explained watch list should contain RELIANCE once')

    explained = explain_watch_candidate(winner)
    if explained.get('grouped_candidate_count') != 2:
        return _fail('explained candidate should preserve grouped_candidate_count')
    if len(explained.get('grouped_prediction_ids') or []) != 2:
        return _fail('explained candidate should preserve grouped_prediction_ids')

    print('TOMORROW_WATCHLIST_DEDUPE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
