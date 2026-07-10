#!/usr/bin/env python3
"""Phase 4B.18G — Feed ticker resolver + fresh news refresh (AstraEdge 52H)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

IST = ZoneInfo('Asia/Kolkata')

SBI_FEED = (
    'SBI raised over $1.5 billion through its new offshore deposit program. '
    'SBI Funds Management is planning an IPO worth approximately $1.2 billion. '
    'SBI Research proposed PSL guideline changes. '
    'SBI Dividend Yield Fund reported 3.6% returns. '
    'Technical analysts suggested selling SBI futures. '
    'SBI shares fell 1.30%.'
)


def _fail(msg: str) -> int:
    print(f'FEED_TICKER_RESOLVER_4B18G_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


@contextmanager
def _isolated_feed_env():
    import sqlite3

    import backend.my_feed.my_feed_db as db_mod

    uri = f'file:feed_resolver_{uuid.uuid4().hex}?mode=memory&cache=shared'
    boot = sqlite3.connect(uri, uri=True, check_same_thread=False)
    boot.row_factory = sqlite3.Row
    boot.executescript(db_mod.SCHEMA)
    boot.commit()
    boot.close()

    def _mem_connect():
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data_dir = Path(tmp)
        news_path = data_dir / 'news_feed.json'
        news_path.write_text(
            json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(), 'items': []}),
            encoding='utf-8',
        )
        import backend.my_feed.feed_verification as fv

        with patch.object(db_mod, '_connect', _mem_connect), patch(
            'backend.my_feed.news_refresh.get_data_path',
            side_effect=lambda name: data_dir / name,
        ), patch.object(fv, 'DATA_DIR', data_dir):
            db_mod.init_my_feed_db()
            yield data_dir


def test_sbi_maps_to_sbin_not_noise() -> int:
    from backend.my_feed.entity_mapping import resolve_company_ticker

    resolved = resolve_company_ticker(SBI_FEED)
    if resolved.get('ticker') != 'SBIN':
        return _fail(f'expected SBIN got {resolved.get("ticker")!r}')
    bad = {'IOC', 'KEC', 'NFL'}
    if bad & set(resolved.get('tickers') or []):
        return _fail(f'SBI mapped to noise tickers {resolved.get("tickers")!r}')
    return 0


def test_state_bank_of_india_maps_to_sbin() -> int:
    from backend.my_feed.entity_mapping import resolve_company_ticker

    resolved = resolve_company_ticker('State Bank of India announces new deposit scheme')
    if resolved.get('ticker') != 'SBIN':
        return _fail(f'expected SBIN got {resolved.get("ticker")!r}')
    if 'State Bank of India' not in str(resolved.get('company') or ''):
        return _fail(f'expected company State Bank of India got {resolved.get("company")!r}')
    return 0


def test_sbi_feed_not_macro_shock() -> int:
    from backend.my_feed.entity_mapping import looks_like_market_wide_macro
    from backend.my_feed.feed_processor import _classify_item

    if looks_like_market_wide_macro(SBI_FEED):
        return _fail('SBI company feed incorrectly treated as market-wide macro')
    classified = _classify_item({'cleaned_summary': SBI_FEED, 'items_found': 1, 'tickers': []})
    if classified.get('macro'):
        return _fail('SBI classified as macro=yes')
    if classified.get('feed_type') != 'company_news':
        return _fail(f'expected company_news got {classified.get("feed_type")!r}')
    return 0


def test_sbi_not_market_risk_alert() -> int:
    from backend.my_feed.feed_processor import _classify_item

    classified = _classify_item({'cleaned_summary': SBI_FEED, 'items_found': 1, 'tickers': []})
    action = str(classified.get('suggested_action') or '')
    if action == 'MARKET RISK ALERT':
        return _fail('SBI company news must not be MARKET RISK ALERT')
    if action not in ('STOCK NEWS', 'WATCH', 'NEWS ONLY', 'WATCH FOR CONFIRMATION'):
        return _fail(f'unexpected action {action!r}')
    return 0


def test_unverified_sbi_still_stores_sbin() -> int:
    from backend.my_feed.feed_processor import ingest_text

    with _isolated_feed_env():
        with patch(
            'backend.my_feed.feed_verification.verify_user_feed_claim',
            side_effect=lambda claim, **kw: {
                'verification_status': 'UNVERIFIED',
                'ticker': 'SBIN',
                'company': 'State Bank of India',
                'entity': 'State Bank of India',
                'tickers': ['SBIN'],
                'feed_type': 'company_news',
                'event_type': 'company_news',
                'side': 'NEUTRAL',
                'ticker_confidence': 'high',
                'auto_refresh': {'attempted': False, 'did_refresh': False},
            },
        ), patch(
            'backend.my_feed.feed_verification.normalize_claim',
            side_effect=lambda text: {
                'raw_user_text': text,
                'claim_summary': text,
                'ticker': 'SBIN',
                'tickers': ['SBIN'],
                'company': 'State Bank of India',
                'entity': 'State Bank of India',
                'ticker_confidence': 'high',
                'feed_type': 'company_news',
                'event_type': 'company_news',
                'side': 'NEUTRAL',
                'keywords': [],
                'resolver_source': 'exact_company_alias',
            },
        ):
            result = ingest_text(SBI_FEED, source='telegram_text')
    record = result.get('record') or {}
    tickers = [str(t).upper() for t in (record.get('tickers') or [])]
    if tickers != ['SBIN']:
        return _fail(f'expected tickers=[SBIN] got {tickers!r} reply={result.get("reply")!r}')
    if any(t in tickers for t in ('IOC', 'KEC', 'NFL')):
        return _fail('noise tickers present')
    return 0


def test_verified_sbi_cache_match() -> int:
    from backend.my_feed.feed_verification import verify_claim_against_sources

    claim = {
        'raw_user_text': SBI_FEED,
        'claim_summary': 'SBI raised over $1.5 billion through offshore deposit program',
        'ticker': 'SBIN',
        'tickers': ['SBIN'],
        'company': 'State Bank of India',
        'entity': 'State Bank of India',
        'keywords': ['sbi', 'raised', 'billion', 'offshore', 'deposit'],
        'event_type': 'company_news',
        'feed_type': 'company_news',
        'side': 'NEUTRAL',
        'ticker_confidence': 'high',
    }
    articles = [{
        'title': 'SBI raises $1.5 billion via offshore deposit program',
        'summary': 'State Bank of India raised funds through a new offshore deposit scheme.',
        'tickers': ['SBIN'],
        'source': 'Moneycontrol',
        'published': datetime.now(timezone.utc).isoformat(),
    }]
    result = verify_claim_against_sources(claim, source_loader=lambda: articles)
    if result.get('verification_status') != 'VERIFIED':
        return _fail(f'expected VERIFIED got {result.get("verification_status")!r}')
    if result.get('ticker') != 'SBIN':
        return _fail(f'verified ticker expected SBIN got {result.get("ticker")!r}')
    return 0


def test_news_refresh_command_exists() -> int:
    from backend.telegram.lazy_command_runner import run_news_only

    with patch(
        'backend.my_feed.news_refresh.run_news_cache_refresh',
        return_value={
            'ok': True,
            'symbol': 'SBIN',
            'company': 'State Bank of India',
            'items_found': 2,
            'new_items': 1,
            'sources_checked': 11,
            'error_count': 0,
            'cache_age_minutes': 0,
            'sources': ['Mint RSS / LiveMint', 'ET Markets'],
        },
    ):
        result = run_news_only(refresh=False, args='refresh SBIN')
    text = str(result.get('text') or '')
    if 'NEWS_REFRESH_DONE' not in text:
        return _fail(f'/news refresh missing NEWS_REFRESH_DONE: {text!r}')
    if 'symbol=SBIN' not in text:
        return _fail(f'/news refresh SBIN missing symbol: {text!r}')
    return 0


def test_news_refresh_sbin_only_news_scope() -> int:
    from backend.my_feed.news_refresh import run_news_cache_refresh

    called = {'unified': False}

    def _fake_unified(**kwargs):
        called['unified'] = True
        return {
            'ok': True,
            'sources_checked': 11,
            'items_found': 10,
            'new_items': 2,
            'errors': [],
            'error_count': 0,
            'sources': ['Mint RSS / LiveMint', 'ET Markets'],
        }

    with patch('backend.collectors.news_provider_registry.run_unified_news_refresh', side_effect=_fake_unified), patch(
        'backend.my_feed.feed_verification.iter_verification_source_articles',
        return_value=[{'title': 'SBI deposit program', 'tickers': ['SBIN'], 'source': 'Reuters'}],
    ):
        result = run_news_cache_refresh(symbol='SBIN', company='State Bank of India')
    if not called.get('unified'):
        return _fail('expected unified news refresh call')
    if result.get('symbol') != 'SBIN':
        return _fail(f'expected symbol SBIN got {result.get("symbol")!r}')
    return 0


def test_feed_verify_updates_status() -> int:
    from backend.my_feed.my_feed_db import get_item, insert_feed_item
    from backend.my_feed.feed_verification import reverify_feed_item

    with _isolated_feed_env():
        record = insert_feed_item({
            'source': 'telegram_text',
            'raw_market_text': SBI_FEED,
            'cleaned_summary': SBI_FEED,
            'tickers': ['SBIN'],
            'event_type': 'company_news',
            'suggested_action': 'WATCH',
            'status': 'active',
            'payload': {
                'verification_status': 'UNVERIFIED',
                'raw_user_text': SBI_FEED,
                'company': 'State Bank of India',
                'feed_type': 'company_news',
            },
        })
        with patch(
            'backend.my_feed.feed_verification.verify_user_feed_claim',
            return_value={
                'verification_status': 'VERIFIED',
                'ticker': 'SBIN',
                'company': 'State Bank of India',
                'entity': 'State Bank of India',
                'source_name': 'Moneycontrol',
                'verified_headline': 'SBI raises $1.5bn via offshore deposits',
                'tickers': ['SBIN'],
                'event_type': 'company_news',
                'feed_type': 'company_news',
                'side': 'NEUTRAL',
                'ticker_confidence': 'high',
            },
        ):
            out = reverify_feed_item(str(record.get('feed_id')))
        refreshed = get_item(str(record.get('feed_id')))
    if out.get('old_status') != 'UNVERIFIED':
        return _fail(f'expected old UNVERIFIED got {out.get("old_status")!r}')
    if out.get('new_status') != 'VERIFIED':
        return _fail(f'expected new VERIFIED got {out.get("new_status")!r}')
    if out.get('ticker') != 'SBIN':
        return _fail(f'verify ticker expected SBIN got {out.get("ticker")!r}')
    if (refreshed or {}).get('verification_status') not in ('VERIFIED', None):
        # payload may hold status
        payload_status = str((refreshed or {}).get('verification_status') or '')
        if payload_status and payload_status != 'VERIFIED':
            return _fail(f'stored status not updated: {refreshed!r}')
    return 0


def test_auto_refresh_when_cache_old() -> int:
    from backend.my_feed.feed_verification import verify_user_feed_claim

    claim = {
        'claim_summary': SBI_FEED,
        'raw_user_text': SBI_FEED,
        'ticker': 'SBIN',
        'tickers': ['SBIN'],
        'company': 'State Bank of India',
        'entity': 'State Bank of India',
        'keywords': ['sbi'],
        'event_type': 'company_news',
        'feed_type': 'company_news',
        'side': 'NEUTRAL',
        'ticker_confidence': 'high',
    }
    refresh_calls = {'n': 0}

    def _refresh(**kwargs):
        refresh_calls['n'] += 1
        return {'ok': True, 'items_found': 1}

    with patch(
        'backend.my_feed.news_refresh.should_auto_refresh_news_for_feed',
        return_value=(True, 'cache_age_90m', 90),
    ), patch(
        'backend.my_feed.news_refresh.run_news_cache_refresh',
        side_effect=_refresh,
    ), patch(
        'backend.my_feed.feed_verification.verify_claim_against_sources',
        return_value={
            'verification_status': 'UNVERIFIED',
            'ticker': 'SBIN',
            'company': 'State Bank of India',
            'entity': 'State Bank of India',
            'tickers': ['SBIN'],
            'side': 'NEUTRAL',
            'event_type': 'company_news',
            'ticker_confidence': 'high',
        },
    ), patch(
        'backend.my_feed.external_verification_search.search_external_verification_articles',
        return_value=[],
    ):
        out = verify_user_feed_claim(claim, allow_auto_refresh=True)
    if refresh_calls['n'] != 1:
        return _fail(f'expected 1 auto refresh got {refresh_calls["n"]}')
    if not (out.get('auto_refresh') or {}).get('did_refresh'):
        return _fail('auto_refresh.did_refresh expected True')
    return 0


def test_no_auto_refresh_when_cache_fresh() -> int:
    from backend.my_feed.feed_verification import verify_user_feed_claim

    claim = {
        'claim_summary': SBI_FEED,
        'raw_user_text': SBI_FEED,
        'ticker': 'SBIN',
        'tickers': ['SBIN'],
        'company': 'State Bank of India',
        'entity': 'State Bank of India',
        'keywords': ['sbi'],
        'event_type': 'company_news',
        'feed_type': 'company_news',
        'side': 'NEUTRAL',
        'ticker_confidence': 'high',
    }
    refresh_calls = {'n': 0}

    with patch(
        'backend.my_feed.news_refresh.should_auto_refresh_news_for_feed',
        return_value=(False, 'cache_fresh_10m', 10),
    ), patch(
        'backend.my_feed.news_refresh.run_news_cache_refresh',
        side_effect=lambda **kw: refresh_calls.__setitem__('n', refresh_calls['n'] + 1),
    ), patch(
        'backend.my_feed.feed_verification.verify_claim_against_sources',
        return_value={
            'verification_status': 'UNVERIFIED',
            'ticker': 'SBIN',
            'company': 'State Bank of India',
            'entity': 'State Bank of India',
            'tickers': ['SBIN'],
            'side': 'NEUTRAL',
            'event_type': 'company_news',
            'ticker_confidence': 'high',
        },
    ), patch(
        'backend.my_feed.external_verification_search.search_external_verification_articles',
        return_value=[],
    ):
        out = verify_user_feed_claim(claim, allow_auto_refresh=True)
    if refresh_calls['n'] != 0:
        return _fail('fresh cache must not auto-refresh')
    if (out.get('auto_refresh') or {}).get('did_refresh'):
        return _fail('did_refresh should be False for fresh cache')
    return 0


def test_macro_feed_still_goes_to_sentinel() -> int:
    from backend.my_feed.entity_mapping import looks_like_market_wide_macro
    from backend.my_feed.feed_processor import _classify_item

    text = 'Sensex and Nifty crash as crude oil jumps 6% after Iran war escalation'
    if not looks_like_market_wide_macro(text):
        return _fail('macro text should look market-wide')
    classified = _classify_item({'cleaned_summary': text, 'items_found': 1, 'tickers': []})
    if not classified.get('macro'):
        return _fail('macro feed must set macro=yes')
    if classified.get('suggested_action') != 'MARKET RISK ALERT':
        return _fail(f'expected MARKET RISK ALERT got {classified.get("suggested_action")!r}')
    return 0


def test_unknown_company_no_random_tickers() -> int:
    from backend.my_feed.entity_mapping import resolve_company_ticker

    resolved = resolve_company_ticker('Some unknown private firm announced a small internal memo')
    if resolved.get('tickers'):
        return _fail(f'unknown text guessed tickers {resolved.get("tickers")!r}')
    if resolved.get('resolver_source') != 'unknown':
        return _fail(f'expected resolver_source=unknown got {resolved.get("resolver_source")!r}')
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


def test_regression_macro_emergency_4b18f() -> int:
    if _run('test_macro_emergency_persistence_4b18f.py') != 0:
        return _fail('52D macro emergency persistence regression failed')
    return 0


def test_regression_macro_shock_sentinel_4b18e() -> int:
    if _run('test_macro_shock_sentinel_4b18e.py') != 0:
        return _fail('52C macro shock sentinel regression failed')
    return 0


def test_regression_live_confirmation_guard_4b18d() -> int:
    if _run('test_live_confirmation_guard_4b18d.py') != 0:
        return _fail('52B live confirmation guard regression failed')
    return 0


def test_build_label_52h() -> int:
    from scripts.test_build_helpers import assert_canonical_build

    err = assert_canonical_build(_fail)
    if err:
        return err
    return 0


def main() -> int:
    tests = [
        test_sbi_maps_to_sbin_not_noise,
        test_state_bank_of_india_maps_to_sbin,
        test_sbi_feed_not_macro_shock,
        test_sbi_not_market_risk_alert,
        test_unverified_sbi_still_stores_sbin,
        test_verified_sbi_cache_match,
        test_news_refresh_command_exists,
        test_news_refresh_sbin_only_news_scope,
        test_feed_verify_updates_status,
        test_auto_refresh_when_cache_old,
        test_no_auto_refresh_when_cache_fresh,
        test_macro_feed_still_goes_to_sentinel,
        test_unknown_company_no_random_tickers,
        test_regression_macro_emergency_4b18f,
        test_regression_macro_shock_sentinel_4b18e,
        test_regression_live_confirmation_guard_4b18d,
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
    print('FEED_TICKER_RESOLVER_4B18G_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
