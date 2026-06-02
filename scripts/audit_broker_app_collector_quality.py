#!/usr/bin/env python3
"""
Audit broker/app collector cache quality.

Prints BROKER_APP_COLLECTOR_QUALITY_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

GENERIC_REJECT = frozenset({'MARKET', 'INDIA', 'STOCK', 'STOCKS', 'SHARE', 'SHARES'})
EXPLICIT_BULLISH_RE = re.compile(
    r'\b(buy|accumulate|outperform|upgrade\s+to\s+buy|must\s+buy|target\s+price|upside)\b',
    re.IGNORECASE,
)
WATCH_TEXT_RE = re.compile(r'\b(stocks?\s+to\s+watch|watchlist|in\s+focus)\b', re.IGNORECASE)


def _fail(msg: str) -> int:
    print(f'BROKER_APP_COLLECTOR_QUALITY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors.broker_app_collector import (
        _dedupe_key,
        _is_valid_ticker,
        _load_known_tickers,
        load_collector_cache,
    )

    cache = load_collector_cache()
    items = cache.get('items') if isinstance(cache.get('items'), list) else []
    known = _load_known_tickers()

    fake_predictions = int(cache.get('fake_predictions') or 0)
    if fake_predictions != 0:
        return _fail(f'fake_predictions={fake_predictions}')

    seen_dedupe: set[str] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            return _fail(f'item {index} is not an object')

        ticker = str(item.get('ticker') or '').strip().upper()
        if not _is_valid_ticker(ticker, known):
            return _fail(f'invalid ticker junk at item {index}: {ticker!r}')
        if ticker in GENERIC_REJECT:
            return _fail(f'generic ticker rejected at item {index}: {ticker}')

        title = str(item.get('headline') or item.get('title') or '')
        source = str(item.get('broker_source') or item.get('source') or '')
        date_part = str(item.get('prediction_date') or item.get('published_at') or '')[:10]
        dedupe = _dedupe_key(source, ticker, title, date_part)
        if dedupe in seen_dedupe:
            return _fail(f'duplicate source+ticker+title at item {index}')
        seen_dedupe.add(dedupe)

        stance = str(item.get('stance') or item.get('direction') or '').upper()
        text = ' '.join(str(item.get(key) or '') for key in ('headline', 'notes', 'title')).strip()
        if stance == 'BULLISH' and WATCH_TEXT_RE.search(text) and not EXPLICIT_BULLISH_RE.search(text):
            return _fail(f'WATCH converted to BULLISH without explicit buy text at item {index}')

        for field in ('source', 'source_type', 'source_reliability', 'extraction_method', 'direction_confidence'):
            if field not in item:
                return _fail(f'missing source quality field {field!r} at item {index}')

    summary = cache.get('summary') if isinstance(cache.get('summary'), dict) else {}
    rejected = int(cache.get('rejected') or summary.get('rejected') or 0)
    rejection_reasons = cache.get('rejection_reasons') or summary.get('rejection_reasons') or {}
    sources = summary.get('sources') or []
    source_count = len(sources)

    print(f'[BROKER_COLLECTOR_QUALITY] items={len(items)} rejected={rejected}')
    print(f'[BROKER_COLLECTOR_QUALITY] rejection_reasons={rejection_reasons}')
    print(f'[BROKER_COLLECTOR_QUALITY] source_count={source_count} fake_predictions={fake_predictions}')
    print(f'[BROKER_COLLECTOR_QUALITY] sources={sources}')
    print('BROKER_APP_COLLECTOR_QUALITY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
