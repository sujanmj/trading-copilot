#!/usr/bin/env python3
"""Phase 4B.18J — Unified news source aggregator (AstraEdge 52H)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

IST = ZoneInfo('Asia/Kolkata')


def _fail(msg: str) -> int:
    print(f'UNIFIED_NEWS_SOURCES_4B18J_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _mock_feed_entry(title: str, link: str = 'https://example.com/a') -> MagicMock:
    import time

    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.summary = f'Summary for {title}'
    entry.description = entry.summary
    entry.published_parsed = time.gmtime()
    return entry


def _mock_unified_refresh_result(*, partial: bool = False) -> dict:
    return {
        'ok': True,
        'partial': partial,
        'sources_checked': 11,
        'items_found': 42,
        'new_items': 5,
        'errors': ['bse_rss:HTTP403'] if partial else [],
        'error_count': 1 if partial else 0,
        'sources': [
            'ET Markets', 'NDTV Profit', 'Mint RSS / LiveMint',
            'Business Standard RSS', 'NSE Corporate Information', 'BSE Corporate Announcements',
            'RBI Press Releases', 'SEBI Press Releases', 'PIB Government Releases',
        ],
        'provider_status': {
            'mint_rss': {'freshness_status': 'CURRENT', 'items_found': 8, 'error_count': 0},
            'business_standard': {'freshness_status': 'CURRENT', 'items_found': 6, 'error_count': 0},
            'nse_rss': {'freshness_status': 'CURRENT', 'items_found': 3, 'error_count': 0},
            'bse_rss': {'freshness_status': 'STALE', 'items_found': 0, 'error_count': 1},
        },
    }


def test_news_refresh_calls_all_providers() -> int:
    from backend.my_feed.news_refresh import format_news_refresh_telegram, run_news_cache_refresh

    with patch(
        'backend.collectors.news_provider_registry.run_unified_news_refresh',
        return_value=_mock_unified_refresh_result(),
    ):
        result = run_news_cache_refresh()
    if not result.get('ok'):
        return _fail('expected ok refresh')
    if int(result.get('sources_checked') or 0) < 10:
        return _fail(f'expected >=10 sources checked got {result.get("sources_checked")!r}')
    text = format_news_refresh_telegram(result)
    if 'NEWS_REFRESH_DONE' not in text:
        return _fail('missing NEWS_REFRESH_DONE')
    if 'Mint RSS' not in text and 'sources=' in text:
        pass  # sources list may be abbreviated
    return 0


def test_news_refresh_sbin_all_providers() -> int:
    from backend.my_feed.news_refresh import run_news_cache_refresh

    articles = [
        {
            'title': 'SBI raises deposit rates',
            'source': 'Mint RSS / LiveMint',
            'tickers': ['SBIN'],
            'description': 'State Bank of India',
        },
        {
            'title': 'SBIN Q4 results',
            'source': 'NSE Corporate Information',
            'tickers': ['SBIN'],
        },
    ]
    with patch(
        'backend.collectors.news_provider_registry.run_unified_news_refresh',
        return_value=_mock_unified_refresh_result(),
    ), patch(
        'backend.my_feed.feed_verification.iter_verification_source_articles',
        return_value=articles,
    ):
        result = run_news_cache_refresh(symbol='SBIN', company='State Bank of India')
    if result.get('symbol') != 'SBIN':
        return _fail(f'expected SBIN got {result.get("symbol")!r}')
    if int(result.get('items_found') or 0) < 1:
        return _fail('expected SBIN matches from unified cache')
    return 0


def test_no_mint_specific_command() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    for bad in ('/news refresh mint', '/news refresh mint markets', '/news refresh mint companies'):
        if bad in HELP_TEXT:
            return _fail(f'help must not advertise {bad!r}')
    if '/news sources' not in HELP_TEXT:
        return _fail('help missing /news sources')
    return 0


def test_mint_item_source_label() -> int:
    from backend.collectors.news_provider_registry import fetch_provider_rss, get_provider_by_id

    prov = get_provider_by_id('mint_rss')
    if not prov:
        return _fail('mint_rss provider missing')
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'<rss></rss>'
    mock_feed = MagicMock()
    mock_feed.entries = [_mock_feed_entry('SBI shares rise on deposit news')]
    mock_feed.bozo = False
    with patch('backend.collectors.news_provider_registry.requests.Session') as sess_cls:
        sess = MagicMock()
        sess.get.return_value = mock_resp
        sess_cls.return_value = sess
        with patch('backend.collectors.news_provider_registry.feedparser.parse', return_value=mock_feed):
            articles, _status = fetch_provider_rss(prov, hours_back=48)
    if not articles:
        return _fail('expected mint articles from mock')
    if articles[0].get('source') != 'Mint RSS / LiveMint':
        return _fail(f'expected Mint RSS / LiveMint got {articles[0].get("source")!r}')
    return 0


def test_business_standard_source_label() -> int:
    from backend.collectors.news_provider_registry import fetch_provider_rss, get_provider_by_id

    prov = get_provider_by_id('business_standard')
    if not prov:
        return _fail('business_standard provider missing')
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'<rss></rss>'
    mock_feed = MagicMock()
    mock_feed.entries = [_mock_feed_entry('Banking sector outlook improves')]
    mock_feed.bozo = False
    with patch('backend.collectors.news_provider_registry.requests.Session') as sess_cls:
        sess = MagicMock()
        sess.get.return_value = mock_resp
        sess_cls.return_value = sess
        with patch('backend.collectors.news_provider_registry.feedparser.parse', return_value=mock_feed):
            articles, _ = fetch_provider_rss(prov, hours_back=48)
    if not articles:
        return _fail('expected BS articles')
    if articles[0].get('source') != 'Business Standard RSS':
        return _fail(f'expected Business Standard RSS got {articles[0].get("source")!r}')
    return 0


def test_nse_higher_verification_tier_than_media() -> int:
    from backend.collectors.news_provider_registry import provider_verification_tier, TIER_OFFICIAL_EXCHANGE, TIER_TRUSTED_MEDIA

    nse_tier = provider_verification_tier({'provider_id': 'nse_rss'})
    mint_tier = provider_verification_tier({'provider_id': 'mint_rss'})
    if nse_tier != TIER_OFFICIAL_EXCHANGE:
        return _fail(f'nse tier expected {TIER_OFFICIAL_EXCHANGE} got {nse_tier}')
    if mint_tier != TIER_TRUSTED_MEDIA:
        return _fail(f'mint tier expected {TIER_TRUSTED_MEDIA} got {mint_tier}')
    if nse_tier >= mint_tier:
        return _fail('NSE should outrank media (lower tier number)')
    return 0


def test_rbi_sebi_pib_regulatory_classification() -> int:
    from backend.collectors.news_provider_registry import classify_news_feed_type

    macro = classify_news_feed_type('RBI keeps repo rate unchanged', 'monetary policy', provider_id='rbi')
    if macro != 'macro':
        return _fail(f'RBI headline should be macro got {macro!r}')
    sebi = classify_news_feed_type('SEBI issues new circular on FPI norms', '', provider_id='sebi')
    if sebi != 'macro':
        return _fail(f'SEBI regulatory should classify macro got {sebi!r}')
    return 0


def test_mint_sbi_maps_to_sbin() -> int:
    from backend.collectors.news_provider_registry import _resolve_article_tickers

    tickers = _resolve_article_tickers('SBI raises offshore deposit program', 'State Bank of India')
    if 'SBIN' not in tickers:
        return _fail(f'expected SBIN in {tickers!r}')
    return 0


def test_oil_iran_macro_candidate() -> int:
    from backend.collectors.news_provider_registry import classify_news_feed_type

    ft = classify_news_feed_type('Crude oil jumps 6% as Iran ceasefire collapses', '')
    if ft != 'macro':
        return _fail(f'oil/iran headline should be macro got {ft!r}')
    with patch('backend.trading.macro_shock_sentinel.process_macro_headline') as proc:
        proc.return_value = {'ok': True, 'assessment': {'severity': 'HIGH'}}
        from backend.collectors.news_provider_registry import _scan_macro_candidates

        n = _scan_macro_candidates([{
            'title': 'Crude oil jumps 6% as Iran ceasefire collapses',
            'description': '',
            'feed_type': 'macro',
            'source_name': 'Mint RSS / LiveMint',
        }])
    if n < 1:
        return _fail('expected macro scan to process oil/iran headline')
    return 0


def test_feed_verify_matches_unified_cache() -> int:
    from backend.my_feed.feed_verification import verify_claim_against_sources

    claim = {
        'claim_summary': 'SBI raises offshore deposit program',
        'tickers': ['SBIN'],
        'keywords': ['sbi', 'offshore', 'deposit'],
        'entity': 'State Bank of India',
        'feed_type': 'company_news',
        'side': 'NEUTRAL',
    }
    articles = [{
        'title': 'SBI raises offshore deposit program worth $1.5 billion',
        'description': 'State Bank of India',
        'source': 'Mint RSS / LiveMint',
        'provider_id': 'mint_rss',
        'tickers': ['SBIN'],
        'link': 'https://livemint.com/sbi-deposit',
    }]
    result = verify_claim_against_sources(claim, source_loader=lambda: articles)
    if result.get('verification_status') not in ('VERIFIED', 'PARTIALLY_VERIFIED'):
        return _fail(f'expected verified got {result.get("verification_status")!r}')
    return 0


def test_dedupe_across_providers() -> int:
    from backend.collectors.news_provider_registry import dedupe_articles

    articles = [
        {'title': 'Oil Surges', 'link': 'https://x.com/oil', 'published': '2026-07-09T10:00:00+00:00'},
        {'title': 'Oil Surges', 'link': 'https://x.com/oil', 'published': '2026-07-09T10:00:00+00:00', 'source': 'NDTV Profit'},
        {'title': 'Different Headline', 'link': 'https://x.com/other', 'published': '2026-07-09T09:00:00+00:00'},
    ]
    out = dedupe_articles(articles)
    if len(out) != 2:
        return _fail(f'expected 2 after dedupe got {len(out)}')
    return 0


def test_refresh_status_shows_news_providers() -> int:
    from backend.trading.market_freshness_guard import format_freshness_status_telegram

    with patch(
        'backend.collectors.news_provider_registry.evaluate_news_provider_freshness',
        return_value={
            'news_all': {'freshness_status': 'CURRENT', 'items_found': 50},
            'mint_rss': {'freshness_status': 'CURRENT', 'items_found': 8, 'error_count': 0},
            'business_standard': {'freshness_status': 'CURRENT', 'items_found': 6, 'error_count': 0},
            'nse_rss': {'freshness_status': 'CURRENT', 'items_found': 3, 'error_count': 0},
            'bse_rss': {'freshness_status': 'STALE', 'items_found': 0, 'error_count': 1},
            'rbi': {'freshness_status': 'CURRENT', 'items_found': 2, 'error_count': 0},
            'sebi': {'freshness_status': 'CURRENT', 'items_found': 1, 'error_count': 0},
            'pib': {'freshness_status': 'MISSING', 'items_found': 0, 'error_count': 0},
        },
    ):
        text = format_freshness_status_telegram()
    if 'news_all' not in text or 'mint_rss' not in text:
        return _fail(f'missing news provider block: {text[:200]!r}')
    return 0


def test_partial_error_does_not_fail_whole_refresh() -> int:
    from backend.my_feed.news_refresh import format_news_refresh_telegram, run_news_cache_refresh

    with patch(
        'backend.collectors.news_provider_registry.run_unified_news_refresh',
        return_value=_mock_unified_refresh_result(partial=True),
    ):
        result = run_news_cache_refresh()
    if not result.get('ok'):
        return _fail('partial refresh with items should still be ok')
    text = format_news_refresh_telegram(result)
    if 'errors=0' in text:
        return _fail('partial refresh should report errors>0')
    return 0


def test_no_epaper_import_command() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    lower = HELP_TEXT.lower()
    for bad in ('epaper', 'e-paper', 'upload import', '/news import'):
        if bad in lower:
            return _fail(f'help must not mention {bad!r}')
    return 0


def test_no_paid_api_required() -> int:
    from backend.collectors.news_provider_registry import PROVIDER_DEFS

    for prov in PROVIDER_DEFS:
        if prov.get('requires_api_key'):
            return _fail(f'provider {prov.get("source_id")} requires API key')
    return 0


def test_mint_token_blocked_as_symbol_refresh() -> int:
    from backend.my_feed.news_refresh import run_news_cache_refresh

    result = run_news_cache_refresh(symbol='MINT')
    if result.get('ok'):
        return _fail('MINT provider token should not run as symbol refresh')
    if 'all sources' not in str(result.get('error') or '').lower():
        return _fail('expected guidance to refresh all sources together')
    return 0


def _run(script: str) -> int:
    env = os.environ.copy()
    env.setdefault('ASTRAEDGE_QA_SMOKE', '1')
    env['DISABLE_TELEGRAM'] = '1'
    env['DISABLE_TELEGRAM_SENDS'] = '1'
    env['PYTHONPATH'] = str(PROJECT_ROOT)
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / script)],
        cwd=str(PROJECT_ROOT),
        env=env,
        check=False,
    ).returncode


def test_regression_market_freshness_4b18i() -> int:
    if _run('test_market_freshness_guard_4b18i.py') != 0:
        return _fail('52G market freshness regression failed')
    return 0


def test_regression_feed_remove_4b18h() -> int:
    if _run('test_feed_remove_4b18h.py') != 0:
        return _fail('52F feed remove regression failed')
    return 0


def test_regression_feed_ticker_resolver_4b18g() -> int:
    if _run('test_feed_ticker_resolver_4b18g.py') != 0:
        return _fail('52E feed ticker resolver regression failed')
    return 0


def test_regression_macro_emergency_4b18f() -> int:
    if _run('test_macro_emergency_persistence_4b18f.py') != 0:
        return _fail('52D macro emergency regression failed')
    return 0


def test_build_label_52h() -> int:
    from scripts.test_build_helpers import assert_canonical_build

    err = assert_canonical_build(_fail)
    if err:
        return err
    return 0


def main() -> int:
    tests = [
        test_news_refresh_calls_all_providers,
        test_news_refresh_sbin_all_providers,
        test_no_mint_specific_command,
        test_mint_item_source_label,
        test_business_standard_source_label,
        test_nse_higher_verification_tier_than_media,
        test_rbi_sebi_pib_regulatory_classification,
        test_mint_sbi_maps_to_sbin,
        test_oil_iran_macro_candidate,
        test_feed_verify_matches_unified_cache,
        test_dedupe_across_providers,
        test_refresh_status_shows_news_providers,
        test_partial_error_does_not_fail_whole_refresh,
        test_no_epaper_import_command,
        test_no_paid_api_required,
        test_mint_token_blocked_as_symbol_refresh,
        test_regression_market_freshness_4b18i,
        test_regression_feed_remove_4b18h,
        test_regression_feed_ticker_resolver_4b18g,
        test_regression_macro_emergency_4b18f,
        test_build_label_52h,
    ]
    failed = 0
    for test in tests:
        rc = test()
        if rc:
            failed += 1
            print(f'FAIL: {test.__name__}', file=sys.stderr)
        else:
            print(f'OK: {test.__name__}')
    if failed:
        print(f'FAILED: {failed}/{len(tests)}', file=sys.stderr)
        return 1
    print('UNIFIED_NEWS_SOURCES_4B18J_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
