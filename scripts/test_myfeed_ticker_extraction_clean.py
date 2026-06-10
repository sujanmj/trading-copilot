#!/usr/bin/env python3
"""Unit tests — clean My Feed ticker extraction (Stage 50C)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

GOLD_NEWS = 'Gold falls below Rs 1.5 lakh amid global sell-off on stronger dollar'
BAD_TICKERS = frozenset({'FALLS', 'BELOW', 'RS', 'LAKH', 'AMID', 'GLOBAL', 'SELL'})


def _fail(msg: str) -> int:
    print(f'MYFEED_TICKER_EXTRACTION_CLEAN_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.text_extractor import extract_tickers, filter_market_text

    tickers = extract_tickers(GOLD_NEWS)
    if 'GOLD' not in tickers:
        return _fail(f'gold news must detect GOLD, got {tickers!r}')
    for bad in BAD_TICKERS:
        if bad in tickers:
            return _fail(f'gold news must not detect junk ticker {bad!r}, got {tickers!r}')

    extracted = filter_market_text(GOLD_NEWS)
    stored_tickers = extracted.get('tickers') or []
    if 'GOLD' not in stored_tickers:
        return _fail(f'filter_market_text must keep GOLD, got {stored_tickers!r}')
    for bad in BAD_TICKERS:
        if bad in stored_tickers:
            return _fail(f'filter_market_text must reject {bad!r}, got {stored_tickers!r}')

    nifty_tickers = extract_tickers('NIFTY gains on banking sector rally today')
    if 'NIFTY' not in nifty_tickers:
        return _fail(f'NIFTY headline must detect NIFTY, got {nifty_tickers!r}')

    print('MYFEED_TICKER_EXTRACTION_CLEAN_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
