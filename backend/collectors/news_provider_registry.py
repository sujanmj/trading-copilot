"""
Unified news provider registry — Phase 4B.18J / AstraEdge 52H.

All /news refresh and scheduled news collection use this registry.
Headlines + short snippets only — no paywalled body scraping.
"""

from __future__ import annotations

import re
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

STAGE = '4B.18J'

SOURCE_TYPE_RSS = 'rss'
SOURCE_TYPE_OFFICIAL = 'official_listing'
SOURCE_TYPE_PUBLIC = 'public_page'

# Verification tiers (lower = higher confidence).
TIER_OFFICIAL_EXCHANGE = 1
TIER_REGULATORY_GOV = 2
TIER_TRUSTED_MEDIA = 3
TIER_USER_UNVERIFIED = 4

OFFICIAL_EXCHANGE_IDS = frozenset({'nse_rss', 'bse_rss'})
REGULATORY_GOV_IDS = frozenset({'rbi', 'sebi', 'pib'})
TRUSTED_MEDIA_IDS = frozenset({
    'et_markets', 'ndtv_profit', 'mint_rss', 'business_standard', 'investing_india', 'mcx',
})

PROVIDER_DEFS: list[dict[str, Any]] = [
    {
        'source_id': 'et_markets',
        'source_name': 'ET Markets',
        'source_type': SOURCE_TYPE_RSS,
        'categories': ['market', 'company'],
        'enabled': True,
        'verification_tier': TIER_TRUSTED_MEDIA,
        'feeds': [
            ('https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms', 'markets'),
            ('https://economictimes.indiatimes.com/markets/rssfeeds/2146842.cms', 'markets'),
        ],
    },
    {
        'source_id': 'ndtv_profit',
        'source_name': 'NDTV Profit',
        'source_type': SOURCE_TYPE_RSS,
        'categories': ['market', 'company'],
        'enabled': True,
        'verification_tier': TIER_TRUSTED_MEDIA,
        'feeds': [('https://feeds.feedburner.com/ndtvprofit-latest', 'market')],
    },
    {
        'source_id': 'mint_rss',
        'source_name': 'Mint RSS / LiveMint',
        'source_type': SOURCE_TYPE_RSS,
        'categories': ['market', 'company', 'sector', 'macro'],
        'enabled': True,
        'verification_tier': TIER_TRUSTED_MEDIA,
        'feeds': [
            ('https://www.livemint.com/rss/markets', 'market'),
            ('https://www.livemint.com/rss/companies', 'company'),
            ('https://www.livemint.com/rss/news', 'news'),
            ('https://www.livemint.com/rss/industry', 'industry'),
            ('https://www.livemint.com/rss/money', 'money'),
        ],
    },
    {
        'source_id': 'business_standard',
        'source_name': 'Business Standard RSS',
        'source_type': SOURCE_TYPE_RSS,
        'categories': ['market', 'company', 'sector', 'banking'],
        'enabled': True,
        'verification_tier': TIER_TRUSTED_MEDIA,
        'feeds': [
            ('https://www.business-standard.com/rss/markets-106.rss', 'market'),
            ('https://www.business-standard.com/rss/latest-news.rss', 'latest'),
            ('https://www.business-standard.com/rss/industry-217.rss', 'industry'),
            ('https://www.business-standard.com/rss/finance-103.rss', 'banking'),
            ('https://www.business-standard.com/rss/companies-101.rss', 'company'),
            ('https://www.business-standard.com/rss/auto-118.rss', 'auto'),
        ],
    },
    {
        'source_id': 'nse_rss',
        'source_name': 'NSE Corporate Information',
        'source_type': SOURCE_TYPE_OFFICIAL,
        'categories': ['company', 'official'],
        'enabled': True,
        'verification_tier': TIER_OFFICIAL_EXCHANGE,
        'feeds': [('https://www.nseindia.com/rss-feed', 'corporate')],
        'fallback_collector': 'nse_announcements',
    },
    {
        'source_id': 'bse_rss',
        'source_name': 'BSE Corporate Announcements',
        'source_type': SOURCE_TYPE_OFFICIAL,
        'categories': ['company', 'official'],
        'enabled': True,
        'verification_tier': TIER_OFFICIAL_EXCHANGE,
        'feeds': [('https://www.bseindia.com/data/xml/notices.xml', 'notices')],
    },
    {
        'source_id': 'rbi',
        'source_name': 'RBI Press Releases',
        'source_type': SOURCE_TYPE_OFFICIAL,
        'categories': ['macro', 'regulatory'],
        'enabled': True,
        'verification_tier': TIER_REGULATORY_GOV,
        'feeds': [('https://www.rbi.org.in/pressreleases_rss.xml', 'press')],
    },
    {
        'source_id': 'sebi',
        'source_name': 'SEBI Press Releases',
        'source_type': SOURCE_TYPE_OFFICIAL,
        'categories': ['regulatory', 'macro'],
        'enabled': True,
        'verification_tier': TIER_REGULATORY_GOV,
        'feeds': [('https://www.sebi.gov.in/sebirss.xml', 'press')],
    },
    {
        'source_id': 'pib',
        'source_name': 'PIB Government Releases',
        'source_type': SOURCE_TYPE_OFFICIAL,
        'categories': ['government', 'macro'],
        'enabled': True,
        'verification_tier': TIER_REGULATORY_GOV,
        'feeds': [('https://pib.gov.in/WriteReadData/rss.aspx?lang=1', 'releases')],
    },
    {
        'source_id': 'investing_india',
        'source_name': 'Investing.com India',
        'source_type': SOURCE_TYPE_RSS,
        'categories': ['market', 'macro'],
        'enabled': True,
        'verification_tier': TIER_TRUSTED_MEDIA,
        'feeds': [('https://in.investing.com/rss/news_285.rss', 'india')],
    },
    {
        'source_id': 'mcx',
        'source_name': 'MCX Press Releases',
        'source_type': SOURCE_TYPE_PUBLIC,
        'categories': ['commodity', 'macro'],
        'enabled': True,
        'verification_tier': TIER_TRUSTED_MEDIA,
        'feeds': [('https://www.mcxindia.com/docs/default-source/market-data/rss/mcxpressrelease.xml', 'press')],
    },
]


def get_enabled_providers() -> list[dict[str, Any]]:
    return [dict(p) for p in PROVIDER_DEFS if p.get('enabled', True)]


def get_provider_by_id(source_id: str) -> dict[str, Any] | None:
    sid = str(source_id or '').strip().lower()
    for prov in PROVIDER_DEFS:
        if str(prov.get('source_id') or '').lower() == sid:
            return dict(prov)
    return None


def provider_verification_tier(article: dict[str, Any]) -> int:
    pid = str(article.get('provider_id') or article.get('source_id') or '').lower()
    if pid in OFFICIAL_EXCHANGE_IDS:
        return TIER_OFFICIAL_EXCHANGE
    if pid in REGULATORY_GOV_IDS:
        return TIER_REGULATORY_GOV
    if pid in TRUSTED_MEDIA_IDS:
        return TIER_TRUSTED_MEDIA
    tier = article.get('verification_tier')
    if isinstance(tier, int):
        return tier
    return TIER_USER_UNVERIFIED


def _strip_html(text: str) -> str:
    return re.sub(r'<[^<]+>', '', str(text or '')).strip()


def _normalize_link(url: str) -> str:
    text = str(url or '').strip()
    if not text:
        return ''
    parsed = urlparse(text)
    return f'{parsed.scheme}://{parsed.netloc}{parsed.path}'.rstrip('/').lower()


def _normalize_headline(title: str) -> str:
    return re.sub(r'\s+', ' ', str(title or '').strip().lower())


def _dedupe_key(article: dict[str, Any]) -> tuple[str, ...]:
    link = _normalize_link(article.get('link') or article.get('url') or '')
    if link:
        return ('link', link)
    title = _normalize_headline(article.get('title') or article.get('headline') or '')
    pub = str(article.get('published') or article.get('published_at') or '')[:10]
    return ('headline', title, pub)


def classify_news_feed_type(title: str, description: str = '', *, provider_id: str = '') -> str:
    blob = f'{title} {description}'.lower()
    if provider_id in REGULATORY_GOV_IDS or provider_id in ('rbi', 'sebi', 'pib'):
        if any(k in blob for k in ('repo rate', 'monetary policy', 'sebi', 'rbi', 'regulation', 'circular')):
            return 'macro'
    if any(k in blob for k in ('ipo', 'fpo', 'offer for sale', 'listing')):
        return 'ipo'
    if any(k in blob for k in ('crude', 'oil', 'iran', 'fed', 'rbi', 'sensex', 'nifty', 'bond yield', 'rupee', 'war', 'ceasefire')):
        return 'macro'
    if any(k in blob for k in ('technical', 'support', 'resistance', 'rsi', 'moving average', 'chart')):
        return 'technical'
    if any(k in blob for k in ('sector', 'industry', 'banking', 'auto', 'aviation', 'agriculture')):
        return 'sector'
    if any(k in blob for k in ('market', 'sensex', 'nifty', 'bse', 'nse', 'stocks', 'shares')):
        return 'market'
    try:
        from backend.intelligence.stock_catalyst_radar import resolve_tickers_from_text

        if resolve_tickers_from_text(blob):
            return 'company'
    except Exception:
        pass
    return 'unknown'


def _resolve_article_tickers(title: str, description: str) -> list[str]:
    blob = f'{title} {description}'.strip()
    tickers: list[str] = []
    try:
        from backend.my_feed.entity_mapping import resolve_company_ticker

        resolved = resolve_company_ticker(blob)
        if resolved.get('ticker'):
            tickers.append(str(resolved['ticker']).upper())
        tickers.extend(str(t).upper() for t in (resolved.get('tickers') or []) if t)
    except Exception:
        pass
    if not tickers:
        try:
            from backend.intelligence.stock_catalyst_radar import resolve_tickers_from_text

            tickers = [str(t).upper() for t in resolve_tickers_from_text(blob)]
        except Exception:
            pass
    try:
        from backend.my_feed.entity_mapping import filter_claim_tickers

        return filter_claim_tickers(blob, tickers)
    except Exception:
        return list(dict.fromkeys(tickers))


def _parse_entry_date(entry: Any) -> datetime | None:
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    if hasattr(entry, 'updated_parsed') and entry.updated_parsed:
        try:
            return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    return None


def fetch_provider_rss(
    provider: dict[str, Any],
    *,
    hours_back: int = 48,
    max_per_feed: int = 25,
    session: requests.Session | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch one provider's RSS feeds. Returns (articles, status_record)."""
    pid = str(provider.get('source_id') or '')
    pname = str(provider.get('source_name') or pid)
    status: dict[str, Any] = {
        'source_id': pid,
        'source_name': pname,
        'enabled': bool(provider.get('enabled', True)),
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'freshness_status': 'MISSING',
        'items_found': 0,
        'error_count': 0,
        'last_error': '',
    }
    articles: list[dict[str, Any]] = []
    sess = session or requests.Session()
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; AstraEdge/52H; +news-refresh)'}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    errors: list[str] = []

    for url, category in provider.get('feeds') or []:
        try:
            resp = sess.get(str(url), headers=headers, timeout=15)
            if resp.status_code != 200:
                errors.append(f'{category}:HTTP{resp.status_code}')
                continue
            feed = feedparser.parse(resp.content)
            for entry in (feed.entries or [])[:max_per_feed]:
                pub = _parse_entry_date(entry)
                if pub and pub < cutoff:
                    continue
                title = str(entry.get('title') or '').strip()
                if not title:
                    continue
                desc = _strip_html(entry.get('summary') or entry.get('description') or '')[:300]
                link = str(entry.get('link') or '').strip()
                feed_type = classify_news_feed_type(title, desc, provider_id=pid)
                tickers = _resolve_article_tickers(title, desc)
                articles.append({
                    'source': pname,
                    'source_name': pname,
                    'provider_id': pid,
                    'source_id': pid,
                    'source_type': provider.get('source_type') or SOURCE_TYPE_RSS,
                    'category': category,
                    'title': title,
                    'headline': title,
                    'description': desc,
                    'summary': desc,
                    'link': link,
                    'url': link,
                    'published': (pub or datetime.now(timezone.utc)).isoformat(),
                    'published_at': (pub or datetime.now(timezone.utc)).isoformat(),
                    'feed_type': feed_type,
                    'tickers': tickers,
                    'symbols': tickers,
                    'verification_tier': provider.get('verification_tier', TIER_TRUSTED_MEDIA),
                    'verification_confidence': (
                        'official' if pid in OFFICIAL_EXCHANGE_IDS
                        else 'regulatory' if pid in REGULATORY_GOV_IDS
                        else 'trusted_media'
                    ),
                    'sentiment_label': 'neutral',
                })
        except Exception as exc:
            errors.append(f'{category}:{str(exc)[:80]}')

    # NSE fallback: ingest from announcements cache if RSS empty.
    if pid == 'nse_rss' and not articles and provider.get('fallback_collector') == 'nse_announcements':
        try:
            import json
            from pathlib import Path

            path = get_data_path('nse_announcements.json')
            if path.is_file():
                payload = json.loads(path.read_text(encoding='utf-8'))
                for bucket in ('high_impact', 'medium_impact', 'announcements', 'items'):
                    for item in (payload.get(bucket) or [])[:20]:
                        if not isinstance(item, dict):
                            continue
                        sym = str(item.get('symbol') or item.get('ticker') or '').upper()
                        subj = str(item.get('subject') or item.get('title') or item.get('headline') or '')
                        if not subj:
                            continue
                        articles.append({
                            'source': pname,
                            'source_name': pname,
                            'provider_id': pid,
                            'source_id': pid,
                            'source_type': SOURCE_TYPE_OFFICIAL,
                            'title': subj,
                            'headline': subj,
                            'description': str(item.get('description') or item.get('desc') or '')[:300],
                            'link': str(item.get('link') or item.get('url') or ''),
                            'url': str(item.get('link') or item.get('url') or ''),
                            'published': datetime.now(timezone.utc).isoformat(),
                            'published_at': datetime.now(timezone.utc).isoformat(),
                            'feed_type': 'company',
                            'tickers': [sym] if sym else [],
                            'symbols': [sym] if sym else [],
                            'verification_tier': TIER_OFFICIAL_EXCHANGE,
                            'verification_confidence': 'official',
                            'sentiment_label': 'neutral',
                        })
        except Exception as exc:
            errors.append(f'nse_cache:{str(exc)[:80]}')

    status['items_found'] = len(articles)
    status['error_count'] = len(errors)
    status['last_error'] = '; '.join(errors[:3])
    if articles:
        status['freshness_status'] = 'CURRENT'
    elif errors:
        status['freshness_status'] = 'STALE'
    else:
        status['freshness_status'] = 'MISSING'
    return articles, status


def dedupe_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    kept: list[dict[str, Any]] = []
    for art in articles:
        if not isinstance(art, dict):
            continue
        key = _dedupe_key(art)
        if key in seen:
            continue
        seen.add(key)
        kept.append(art)
    kept.sort(key=lambda a: str(a.get('published') or a.get('published_at') or ''), reverse=True)
    return kept


def _scan_macro_candidates(articles: list[dict[str, Any]], *, send_alerts: bool = False) -> int:
    """Pass macro headlines into macro_shock_sentinel (no LLM)."""
    count = 0
    try:
        from backend.trading.macro_shock_sentinel import process_macro_headline
    except Exception:
        return 0
    for art in articles[:80]:
        if not isinstance(art, dict):
            continue
        if str(art.get('feed_type') or '') not in ('macro', 'market', 'unknown', 'sector'):
            blob = f"{art.get('title') or ''} {art.get('description') or ''}".lower()
            if not any(k in blob for k in ('oil', 'crude', 'iran', 'sensex', 'nifty', 'fed', 'rbi', 'sebi', 'bond', 'rupee', 'war')):
                continue
        headline = str(art.get('title') or art.get('headline') or '').strip()
        if len(headline) < 12:
            continue
        try:
            result = process_macro_headline(
                headline,
                source=str(art.get('source_name') or art.get('source') or ''),
                item=art,
                send_fn=None,
                store_memory=True,
            )
            if result.get('assessment'):
                count += 1
        except Exception:
            pass
    return count


def run_unified_news_refresh(
    *,
    hours_back: int = 48,
    send_macro_alerts: bool = False,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """
    Refresh all enabled news providers into news_feed.json + live_news_feed.json.
    Partial success: one provider failure does not abort others.
    """
    providers = get_enabled_providers()
    all_articles: list[dict[str, Any]] = []
    provider_status: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    sources_checked = 0

    for prov in providers:
        sources_checked += 1
        pid = str(prov.get('source_id') or '')
        try:
            batch, status = fetch_provider_rss(prov, hours_back=hours_back, session=session)
            all_articles.extend(batch)
            provider_status[pid] = status
            if status.get('last_error'):
                errors.append(f"{pid}:{status.get('last_error')}")
        except Exception as exc:
            provider_status[pid] = {
                'source_id': pid,
                'source_name': prov.get('source_name'),
                'enabled': True,
                'last_updated': datetime.now(timezone.utc).isoformat(),
                'freshness_status': 'STALE',
                'items_found': 0,
                'error_count': 1,
                'last_error': str(exc)[:120],
            }
            errors.append(f'{pid}:{exc}')

    deduped = dedupe_articles(all_articles)
    prior_count = 0
    news_path = get_data_path('news_feed.json')
    try:
        import json

        if news_path.is_file():
            prior = json.loads(news_path.read_text(encoding='utf-8'))
            prior_count = len(prior.get('articles') or prior.get('items') or [])
    except Exception:
        prior_count = 0

    new_items = max(0, len(deduped) - prior_count)
    macro_scanned = _scan_macro_candidates(deduped, send_alerts=send_macro_alerts)

    now_iso = datetime.now(timezone.utc).isoformat()
    ok_count = sum(1 for s in provider_status.values() if s.get('freshness_status') == 'CURRENT')
    fail_count = sum(1 for s in provider_status.values() if s.get('error_count', 0) > 0 and not s.get('items_found'))

    output = {
        'last_updated': now_iso,
        'generated_at': now_iso,
        'total_articles': len(deduped),
        'items_found': len(deduped),
        'new_items': new_items,
        'sources_checked': sources_checked,
        'feeds_ok': ok_count,
        'feeds_failed': fail_count,
        'errors': errors[:12],
        'provider_registry': provider_status,
        'provider_status': provider_status,
        'articles': deduped,
        'macro_candidates_scanned': macro_scanned,
        'stage': STAGE,
    }

    for path_name in ('news_feed.json', 'live_news_feed.json'):
        atomic_write_json(get_data_path(path_name), output)

    source_labels = sorted({
        str(s.get('source_name') or s.get('source_id') or '')
        for s in provider_status.values()
        if s.get('items_found', 0) > 0 or s.get('freshness_status') == 'CURRENT'
    })
    if not source_labels:
        source_labels = [str(p.get('source_name') or '') for p in providers[:6]]

    return {
        'ok': ok_count > 0 or len(deduped) > 0,
        'partial': bool(errors) and len(deduped) > 0,
        'sources_checked': sources_checked,
        'items_found': len(deduped),
        'new_items': new_items,
        'errors': errors,
        'error_count': len(errors),
        'sources': source_labels,
        'provider_status': provider_status,
        'output': output,
    }


def load_provider_status_from_cache() -> dict[str, dict[str, Any]]:
    try:
        import json

        path = get_data_path('news_feed.json')
        if not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding='utf-8'))
        reg = payload.get('provider_registry') or payload.get('provider_status') or {}
        return dict(reg) if isinstance(reg, dict) else {}
    except Exception:
        return {}


def evaluate_news_provider_freshness(*, stale_after_minutes: int = 180) -> dict[str, Any]:
    """Aggregate + per-provider freshness for /refresh status."""
    from backend.trading.market_freshness_guard import (
        FRESHNESS_CURRENT,
        FRESHNESS_MISSING,
        FRESHNESS_STALE,
        _age_minutes,
        _format_ist,
        _parse_ts,
        _session_date,
    )

    try:
        import json

        path = get_data_path('news_feed.json')
        payload = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except Exception:
        payload = {}

    ts = _parse_ts(payload.get('last_updated') or payload.get('generated_at'))
    age = _age_minutes(ts)
    reg = load_provider_status_from_cache()
    any_current = any(str(v.get('freshness_status') or '') == 'CURRENT' for v in reg.values())
    if not payload.get('articles'):
        news_all = FRESHNESS_MISSING
    elif age is not None and age > stale_after_minutes:
        news_all = FRESHNESS_STALE
    elif any_current or payload.get('articles'):
        news_all = FRESHNESS_CURRENT
    else:
        news_all = FRESHNESS_STALE

    table: dict[str, dict[str, Any]] = {
        'news_all': {
            'freshness_status': news_all,
            'last_updated_ist': _format_ist(ts),
            'age_minutes': age,
            'items_found': len(payload.get('articles') or []),
        },
    }
    for prov in PROVIDER_DEFS:
        pid = str(prov.get('source_id') or '')
        rec = dict(reg.get(pid) or {})
        if not rec:
            rec = {
                'freshness_status': FRESHNESS_MISSING,
                'items_found': 0,
                'error_count': 0,
                'last_error': '',
            }
        table[pid] = {
            'freshness_status': rec.get('freshness_status') or FRESHNESS_MISSING,
            'last_updated_ist': _format_ist(_parse_ts(rec.get('last_updated'))),
            'age_minutes': _age_minutes(_parse_ts(rec.get('last_updated'))),
            'items_found': rec.get('items_found', 0),
            'error_count': rec.get('error_count', 0),
            'last_error': str(rec.get('last_error') or '')[:80],
        }
    return table


def format_news_sources_telegram() -> str:
    """Admin/debug: /news sources — enabled providers + freshness."""
    table = evaluate_news_provider_freshness()
    lines = ['<b>/news sources</b>', '', '<b>ENABLED NEWS PROVIDERS</b>']
    for prov in get_enabled_providers():
        pid = str(prov.get('source_id') or '')
        rec = table.get(pid) or {}
        status = str(rec.get('freshness_status') or 'MISSING')
        items = int(rec.get('items_found') or 0)
        errs = int(rec.get('error_count') or 0)
        err_part = f' · errors={errs}' if errs else ''
        lines.append(f"{prov.get('source_name')}: {status} · items={items}{err_part}")
    agg = table.get('news_all') or {}
    lines.extend([
        '',
        f"news_all: {agg.get('freshness_status', 'MISSING')} · total={agg.get('items_found', 0)}",
        '<i>Headlines/snippets only · no paywall scraping</i>',
    ])
    return '\n'.join(lines)
