#!/usr/bin/env python3
"""
Validate tomorrow watchlist ticker deduplication.

Prints exactly TOMORROW_WATCHLIST_DEDUPE_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / 'data' / 'tomorrow_watchlist_report.json'


def _fail(msg: str) -> int:
    print(f'TOMORROW_WATCHLIST_DEDUPE_FAIL: {msg}', file=sys.stderr)
    return 1


def _unique_tickers(items: list[dict]) -> list[str]:
    return [str(item.get('ticker') or '').strip().upper() for item in items if item.get('ticker')]


def _assert_unique(section: str, items: list[dict]) -> str | None:
    tickers = _unique_tickers(items)
    if len(tickers) != len(set(tickers)):
        dupes = sorted({t for t in tickers if tickers.count(t) > 1})
        return f'duplicate ticker(s) in {section}: {dupes}'
    return None


def main() -> int:
    if not REPORT_PATH.is_file():
        return _fail(f'missing report: {REPORT_PATH}')

    report = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
    if report.get('ok') is not True:
        return _fail('report ok != true')

    summary = report.get('summary') or {}
    duplicates_removed = int(summary.get('duplicates_removed') or 0)
    if duplicates_removed < 0:
        return _fail('duplicates_removed must be >= 0')

    for section, key in (
        ('top_watchlist', 'top_watchlist'),
        ('avoid', 'avoid'),
        ('no_decision', 'no_decision'),
    ):
        err = _assert_unique(section, report.get(key) or [])
        if err:
            return _fail(err)

    if duplicates_removed > 0:
        grouped_found = False
        for item in (report.get('top_watchlist') or []) + (report.get('avoid') or []) + (report.get('no_decision') or []):
            ids = item.get('grouped_prediction_ids') or []
            if len(ids) > 1:
                grouped_found = True
                break
        if not grouped_found:
            return _fail('duplicates_removed > 0 but grouped_prediction_ids not found')

    print(f'[TOMORROW_DEDUPE] raw_candidates={summary.get("raw_candidates", 0)}')
    print(f'[TOMORROW_DEDUPE] unique_tickers={summary.get("unique_tickers", 0)}')
    print(f'[TOMORROW_DEDUPE] duplicates_removed={duplicates_removed}')
    print('TOMORROW_WATCHLIST_DEDUPE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
