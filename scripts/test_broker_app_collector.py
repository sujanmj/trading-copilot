#!/usr/bin/env python3
"""
Smoke test for broker/app collector (offline parsing, no network required).

Usage:
  python scripts/test_broker_app_collector.py

Prints exactly BROKER_APP_COLLECTOR_TEST_OK on success.
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
    print(f'BROKER_APP_COLLECTOR_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_prediction_intelligence import is_outcome_evidence
    from backend.collectors.broker_app_collector import (
        VALID_SOURCES,
        _headline_is_pick_candidate,
        article_to_inbox_items,
        collect_from_manual_inbox,
        extract_tickers_from_text,
        normalize_collected_item,
    )

    known = {'RELIANCE', 'TCS', 'INFY', 'HDFCBANK'}

    if not _headline_is_pick_candidate('Stocks to watch today: RELIANCE, TCS'):
        return _fail('pick headline not detected')
    if _headline_is_pick_candidate('Top gainers today: Nifty ends higher'):
        return _fail('outcome headline should not be pick candidate')

    tickers = extract_tickers_from_text('Stocks to watch: RELIANCE and TCS gain traction', known)
    if tickers != ['RELIANCE', 'TCS']:
        return _fail(f'ticker extraction failed: {tickers}')

    alias_tickers = extract_tickers_from_text(
        'Stocks to watch: Tata Power and HDFC Bank',
        known | {'TATAPOWER', 'HDFCBANK'},
    )
    if 'TATAPOWER' not in alias_tickers or 'HDFCBANK' not in alias_tickers:
        return _fail(f'company alias extraction failed: {alias_tickers}')

    normalized = normalize_collected_item({
        'broker_source': 'TestBroker',
        'ticker': 'RELIANCE',
        'stance': 'WATCH',
        'prediction_date': '2026-05-30',
        'headline': 'Stocks to watch: RELIANCE',
    }, 'manual')
    if normalized is None:
        return _fail('normalize_collected_item returned None')
    if normalized.get('collector_source') != 'manual':
        return _fail('collector_source not preserved')
    if not str(normalized.get('prediction_id') or '').startswith('broker:'):
        return _fail('prediction_id must start with broker:')

    items, reason = article_to_inbox_items(
        feed_name='Moneycontrol Markets',
        title='Stocks to watch: RELIANCE, TCS on radar',
        description='Broker picks ahead of results — accumulate on dips for RELIANCE',
        link='https://example.com/stocks-to-watch',
        published_at=None,
        known_tickers=known,
    )
    if reason is not None or not items:
        return _fail(f'expected inbox items, got reason={reason}')

    rejected, rej_reason = article_to_inbox_items(
        feed_name='Moneycontrol Markets',
        title='Top gainers today: RELIANCE jumps 3%',
        description='EOD movers list',
        link='https://example.com/top-gainers',
        published_at=None,
        known_tickers=known,
    )
    if rejected:
        return _fail('outcome headline should produce no items')

    if not is_outcome_evidence({'target_type': 'eod_gainer', 'ticker': 'RELIANCE'}):
        return _fail('sanity: eod_gainer is outcome evidence')

    manual = collect_from_manual_inbox(str(PROJECT_ROOT / 'data' / 'broker_prediction_inbox.example.json'))
    if not isinstance(manual, list):
        return _fail('collect_from_manual_inbox must return list')

    if 'all' not in VALID_SOURCES or 'tv' not in VALID_SOURCES:
        return _fail('VALID_SOURCES incomplete')

    print('BROKER_APP_COLLECTOR_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
