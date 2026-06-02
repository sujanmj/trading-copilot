#!/usr/bin/env python3
"""
Unit tests for external evidence classifier (Stage 39C).

Prints EXTERNAL_EVIDENCE_CLASSIFIER_OK on success.
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
    print(f'EXTERNAL_EVIDENCE_CLASSIFIER_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors.external_evidence_classifier import (
        classify_direction,
        classify_external_item,
        classify_market_relevance,
        extract_company_or_ticker,
    )

    universe = {
        'tickers': {'RELIANCE', 'ICICIBANK', 'SUZLON', 'TCS', 'NIFTY50', 'OLAELEC', 'CUMMINSIND', 'AUBANK'},
        'aliases': {
            'reliance': 'RELIANCE',
            'reliance industries': 'RELIANCE',
            'icici bank': 'ICICIBANK',
            'suzlon': 'SUZLON',
            'ola electric': 'OLAELEC',
            'cummins india': 'CUMMINSIND',
            'au small finance bank': 'AUBANK',
        },
    }

    broker = classify_external_item({
        'title': 'Nomura upgrades ICICI Bank to Buy with target price Rs 1,500',
        'description': 'Brokerage recommends accumulate on dips',
        'source': 'Economic Times',
    }, universe)
    if broker['classification'] != 'broker_prediction_candidate':
        return _fail(f'broker sample: {broker["classification"]}')
    if broker['ticker'] != 'ICICIBANK':
        return _fail(f'broker ticker: {broker["ticker"]}')
    if broker['direction'] != 'BULLISH':
        return _fail(f'broker direction: {broker["direction"]}')

    stock_news = classify_external_item({
        'title': 'Supreme Court provides relief to Reliance in 2007 securities market fraud case',
        'description': 'Reliance Industries Ltd received relief from Supreme Court',
        'source': 'Economic Times',
    }, universe)
    if stock_news['classification'] != 'stock_news_evidence':
        return _fail(f'stock news: {stock_news["classification"]}')
    if stock_news['ticker'] != 'RELIANCE':
        return _fail(f'stock news ticker: {stock_news["ticker"]}')
    if stock_news['direction'] == 'BULLISH':
        return _fail('stock news must not be BULLISH without explicit buy')

    market = classify_external_item({
        'title': 'Sensex, Nifty slide 1.5% as MSCI rejig triggers late-hour market selloff',
        'source': 'Business Standard',
    }, universe)
    if market['classification'] != 'market_context':
        return _fail(f'market context: {market["classification"]}')
    if market['direction'] != 'NEUTRAL':
        return _fail(f'market direction: {market["direction"]}')

    macro = classify_external_item({
        'title': 'Oil prices slip as U.S.-Iran deal awaited; Brent set for worst month since 2020',
        'source': 'Investing.com',
    }, universe)
    if macro['classification'] != 'macro_context':
        return _fail(f'macro context: {macro["classification"]}')

    reject = classify_external_item({
        'title': 'GT vs RR, Qualifier 2 Highlights: Gill Century Powers Gujarat Into IPL 2026 Final',
        'source': 'NDTV Profit',
    }, universe)
    if reject['classification'] != 'reject':
        return _fail(f'reject sports: {reject["classification"]}')
    if not reject['rejection_reason']:
        return _fail('reject must have rejection_reason')

    watch = classify_external_item({
        'title': 'Stocks to watch today: Reliance, TCS in focus',
        'source': 'Moneycontrol',
    }, universe)
    if watch['direction'] != 'WATCH':
        return _fail(f'watch direction: {watch["direction"]}')

    dir_watch = classify_direction('Stocks to watch today: RELIANCE')
    if dir_watch['direction'] != 'WATCH':
        return _fail(f'classify_direction watch: {dir_watch}')

    dir_bull = classify_direction('Broker recommends buy with target price upside')
    if dir_bull['direction'] != 'BULLISH':
        return _fail(f'classify_direction bullish: {dir_bull}')

    dir_bear = classify_direction('Analyst says avoid and downgrade to sell')
    if dir_bear['direction'] != 'BEARISH':
        return _fail(f'classify_direction bearish: {dir_bear}')

    extracted = extract_company_or_ticker('ICICI Bank shares rise on strong Q4', universe)
    if extracted['ticker'] != 'ICICIBANK':
        return _fail(f'alias extract: {extracted}')

    relevance = classify_market_relevance('Nifty ends lower; Sensex down 500 points')
    if relevance['relevance'] != 'market_context':
        return _fail(f'market relevance: {relevance}')

    ola = classify_external_item({
        'title': "Ola Electric shares jump 9%, skyrocket 93% in 2 months. What's fuelling the rally?",
        'description': (
            'Ola Electric shares surged after reporting a narrower quarterly loss. '
            'Brokerages remain cautious on the long-term recovery outlook.'
        ),
        'source': 'Economic Times',
    }, universe)
    if ola['classification'] != 'stock_news_evidence':
        return _fail(f'Ola rally should be stock_news_evidence: {ola["classification"]}')
    if ola['classification'] == 'broker_prediction_candidate':
        return _fail('Ola rally must not be broker_prediction_candidate')

    nomura = classify_external_item({
        'title': 'Nomura downgrades Cummins India to Neutral despite raising target price',
        'description': 'Brokerage cut rating but lifted price target to Rs 3,200',
        'source': 'Moneycontrol',
    }, universe)
    if nomura['classification'] != 'broker_prediction_candidate':
        return _fail(f'Nomura downgrade should be broker candidate: {nomura["classification"]}')
    if nomura['direction'] == 'BULLISH':
        return _fail(f'Nomura downgrade/neutral must not be BULLISH: {nomura["direction"]}')
    if not nomura.get('negative_override_applied'):
        return _fail('Nomura downgrade should set negative_override_applied')

    top_picks = classify_external_item({
        'title': 'ICICI Bank, AU Small Finance Bank top picks for June: Brokerages',
        'description': 'Analysts highlight ICICI Bank as preferred pick',
        'source': 'Economic Times',
    }, universe)
    if top_picks['classification'] != 'broker_prediction_candidate':
        return _fail(f'top picks should be broker candidate: {top_picks["classification"]}')
    if top_picks['direction'] != 'BULLISH':
        return _fail(f'top picks should be BULLISH: {top_picks["direction"]}')

    watch_only = classify_external_item({
        'title': 'Stocks to watch today: Reliance, TCS in focus',
        'description': 'Market movers to track',
        'source': 'Moneycontrol',
    }, universe)
    if watch_only['direction'] == 'BULLISH':
        return _fail('stocks to watch must not be BULLISH')

    crash_downgrade = classify_external_item({
        'title': 'Reliance shares crash 8% after analyst downgrade to sell',
        'description': 'Stock slumps following brokerage downgrade',
        'source': 'Livemint',
    }, universe)
    if crash_downgrade['direction'] not in {'BEARISH', 'WATCH'}:
        return _fail(f'crash after downgrade direction: {crash_downgrade["direction"]}')
    if not crash_downgrade.get('negative_override_applied'):
        return _fail('crash after downgrade should apply negative override')

    target_neutral = classify_external_item({
        'title': 'Broker raises target price but maintains neutral rating on Suzlon',
        'description': 'Analyst lifted price target while keeping neutral stance',
        'source': 'Business Standard',
    }, universe)
    if target_neutral['direction'] == 'BULLISH':
        return _fail(f'target raised with neutral must not be BULLISH: {target_neutral["direction"]}')
    if target_neutral['direction'] not in {'WATCH', 'NEUTRAL'}:
        return _fail(f'target raised with neutral direction: {target_neutral["direction"]}')

    for sample in (broker, nomura, top_picks, ola):
        if not sample.get('classification_reason'):
            return _fail('classified item missing classification_reason')
        if not sample.get('direction_reason'):
            return _fail('classified item missing direction_reason')

    print('EXTERNAL_EVIDENCE_CLASSIFIER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
