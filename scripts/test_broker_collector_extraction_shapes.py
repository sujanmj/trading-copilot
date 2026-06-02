#!/usr/bin/env python3
"""
Offline shape tests for broker/app collector extraction (Stage 39B).

Prints BROKER_COLLECTOR_EXTRACTION_SHAPES_OK on success.
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
    print(f'BROKER_COLLECTOR_EXTRACTION_SHAPES_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors.broker_app_collector import (
        _articles_from_json_payload,
        _extract_tv_records,
        article_to_inbox_items,
        evaluate_news_record,
        evaluate_tv_record,
        extract_tickers_from_text,
        normalize_collected_item,
    )

    known = {'RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'WIPRO', 'ICICIBANK'}

    articles = _articles_from_json_payload({'items': [{'title': 'Stocks to watch: RELIANCE'}]}, 'Test')
    if len(articles) != 1:
        return _fail(f'dict.items extraction failed: {len(articles)}')

    articles = _articles_from_json_payload({'articles': [{'headline': 'Top picks: TCS'}]}, 'Test')
    if len(articles) != 1:
        return _fail('dict.articles extraction failed')

    list_rows = _articles_from_json_payload([{'title': 'Buy INFY on dips'}], 'Test')  # type: ignore[arg-type]
    if len(list_rows) != 1:
        return _fail('list root extraction failed')

    nested = _articles_from_json_payload({'feed': {'entries': [{'title': 'Stocks to watch: HDFCBANK'}]}}, 'Test')
    if len(nested) != 1:
        return _fail('nested entries extraction failed')

    tv_rows = _extract_tv_records({'videos': [{'title': 'Stock picks today', 'symbols': ['WIPRO']}]})
    if len(tv_rows) != 1:
        return _fail('TV videos extraction failed')

    title_tickers = extract_tickers_from_text('Stocks to watch: RELIANCE and TCS', known)
    if 'RELIANCE' not in title_tickers:
        return _fail('title ticker extraction failed')

    no_ticker_rows, no_ticker_rej = evaluate_news_record(
        {'title': 'Stocks to watch today', 'topics': ['banking']},
        feed_name='Test',
        known_tickers=known,
    )
    if no_ticker_rows or (no_ticker_rej or {}).get('reason') != 'no_ticker':
        return _fail(f'expected no_ticker rejection, got rows={no_ticker_rows} rej={no_ticker_rej}')

    watch_items, watch_reason = article_to_inbox_items(
        feed_name='Moneycontrol',
        title='Stocks to watch: ICICIBANK on radar',
        description='Keep ICICIBANK on watchlist ahead of results',
        link='https://example.com/watch',
        published_at=None,
        known_tickers=known,
    )
    if watch_reason or not watch_items:
        return _fail(f'watch headline failed: reason={watch_reason}')
    if watch_items[0].get('stance') != 'WATCH':
        return _fail('watch headline should normalize to WATCH')

    bull = normalize_collected_item({
        'broker_source': 'Test',
        'ticker': 'TCS',
        'headline': 'Buy TCS with upside — accumulate on dips',
        'prediction_date': '2026-05-30',
    }, 'manual')
    if bull is None or bull.get('stance') != 'BULLISH':
        return _fail('explicit buy should normalize to BULLISH')

    tv_rows_out, tv_rej = evaluate_tv_record(
        {
            'title': 'Stock Market LIVE Updates with WIPRO focus',
            'channel': 'CNBC-TV18',
            'symbols': ['WIPRO', 'NIFTY'],
            'topics': ['stock market'],
        },
        known_tickers=known,
    )
    if tv_rej or not tv_rows_out or tv_rows_out[0].get('ticker') != 'WIPRO':
        return _fail(f'TV WIPRO extraction failed: rows={tv_rows_out} rej={tv_rej}')

    print('BROKER_COLLECTOR_EXTRACTION_SHAPES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
