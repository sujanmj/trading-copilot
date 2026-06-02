#!/usr/bin/env python3
"""
Offline tests for external source coverage collector (Stage 39).

Prints EXTERNAL_SOURCE_COVERAGE_TEST_OK on success.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'EXTERNAL_SOURCE_COVERAGE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors import broker_app_collector as bac
    from backend.utils.config import DATA_DIR

    known = {'RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'WIPRO'}

    tickers = bac.extract_tickers_from_text('Stocks to watch: RELIANCE and TCS', known)
    if tickers != ['RELIANCE', 'TCS']:
        return _fail(f'ticker extraction failed: {tickers}')

    junk = bac.extract_tickers_from_text('MARKET and INDIA outlook', known | {'MARKET', 'INDIA'})
    if any(t in {'MARKET', 'INDIA'} for t in junk):
        return _fail(f'generic terms should be rejected: {junk}')

    watch_norm = bac.normalize_collected_item({
        'broker_source': 'Test',
        'ticker': 'RELIANCE',
        'stance': 'WATCH',
        'headline': 'Stocks to watch: RELIANCE on radar',
        'prediction_date': '2026-05-30',
    }, 'manual')
    if watch_norm is None or watch_norm.get('stance') != 'WATCH':
        return _fail('WATCH must stay WATCH')
    if watch_norm.get('direction_confidence') != 'watch_only':
        return _fail('watch headline should be watch_only confidence')

    bull_norm = bac.normalize_collected_item({
        'broker_source': 'Test',
        'ticker': 'TCS',
        'headline': 'Buy TCS with target upside — accumulate on dips',
        'prediction_date': '2026-05-30',
    }, 'manual')
    if bull_norm is None or bull_norm.get('stance') != 'BULLISH':
        return _fail('explicit buy should become BULLISH')
    if bull_norm.get('direction_confidence') != 'explicit':
        return _fail('explicit buy should have explicit direction_confidence')

    bear_norm = bac.normalize_collected_item({
        'broker_source': 'Test',
        'ticker': 'INFY',
        'headline': 'Avoid INFY — sell on weakness, downside risk',
        'prediction_date': '2026-05-30',
    }, 'manual')
    if bear_norm is None or bear_norm.get('stance') != 'BEARISH':
        return _fail('explicit avoid/sell should become BEARISH')

    items, reason = bac.article_to_inbox_items(
        feed_name='Moneycontrol Markets',
        title='Top gainers today: RELIANCE jumps',
        description='EOD movers list',
        link='https://example.com/gainers',
        published_at=None,
        known_tickers=known,
    )
    if items:
        return _fail('EOD gainers should not produce items')

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        universe_file = tmp_path / 'historical_ticker_universe.json'
        universe_file.write_text(json.dumps({
            'tickers': [{'ticker': t} for t in sorted(known)],
        }), encoding='utf-8')

        news_file = tmp_path / 'news_feed.json'
        news_file.write_text(json.dumps({
            'articles': [{
                'title': 'Stocks to watch: RELIANCE, TCS in focus',
                'description': 'Analysts flag RELIANCE for watchlist ahead of results',
                'source': 'Moneycontrol',
                'link': 'https://example.com/watch',
            }],
        }), encoding='utf-8')

        tv_file = tmp_path / 'tv_intelligence.json'
        tv_file.write_text(json.dumps({
            'videos': [{
                'title': 'Stocks to watch today',
                'description': 'HDFCBANK and WIPRO on radar',
                'channel': 'CNBC-TV18',
                'topics': ['stocks to watch'],
                'url': 'https://example.com/tv',
            }],
        }), encoding='utf-8')

        manual_file = tmp_path / 'broker_prediction_inbox.json'
        manual_file.write_text(json.dumps({
            'items': [{
                'broker_source': 'Manual Test',
                'ticker': 'RELIANCE',
                'stance': 'WATCH',
                'headline': 'Manual watch RELIANCE',
                'prediction_date': '2026-05-30',
            }],
        }), encoding='utf-8')

        orig_data = bac.DATA_DIR
        bac.DATA_DIR = tmp_path
        bac.OUTPUT_FILE = tmp_path / 'broker_prediction_inbox.json'
        bac.CACHE_FILE = tmp_path / 'broker_app_collector_latest.json'
        try:
            news_rows = bac.collect_from_existing_news(limit=10)
            if not news_rows:
                return _fail('mock news produced no rows')

            tv_rows = bac.collect_from_tv_intelligence(limit=10)
            if not tv_rows:
                return _fail('mock tv produced no rows')

            manual_rows = bac.collect_from_manual_inbox(str(manual_file))
            if len(manual_rows) != 1:
                return _fail('manual inbox mock failed')

            result = bac.collect_broker_app_predictions(
                limit=20,
                dry_run=True,
                source='all',
                write_broker_db=False,
            )
            if result.get('fake_predictions', 0) != 0:
                return _fail('fake_predictions must be 0')
            if result.get('written_to_db', 0) != 0:
                return _fail('collect must not write DB unless requested')

            normalized = result.get('items') or []
            dedupe_keys = []
            for row in normalized:
                raw = row.get('raw_payload') or {}
                dedupe_keys.append(raw.get('dedupe_key'))
                if row.get('stance') == 'WATCH' and row.get('direction_confidence') == 'explicit':
                    return _fail('WATCH row must not have explicit confidence without buy text')
            if len(dedupe_keys) != len(set(k for k in dedupe_keys if k)):
                return _fail('dedupe failed in collect run')
        finally:
            bac.DATA_DIR = orig_data
            bac.OUTPUT_FILE = orig_data / 'broker_prediction_inbox.json'
            bac.CACHE_FILE = orig_data / 'broker_app_collector_latest.json'

    coverage = bac.get_external_source_coverage()
    if coverage.get('ok') is not True:
        return _fail('get_external_source_coverage failed')

    print('EXTERNAL_SOURCE_COVERAGE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
