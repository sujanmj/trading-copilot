"""Persist automatically collected, source-attributed news in My Feed.

Articles remain explicitly UNVERIFIED until the existing verification flow confirms
their claims. This module stores headlines and short provider snippets only.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.my_feed.feed_processor import _classify_item
from backend.my_feed.my_feed_db import get_item, insert_feed_item
from backend.my_feed.text_extractor import extract_tickers


AUTO_NEWS_SOURCE = 'auto_news'
SUPPORTED_PROVIDER_IDS = frozenset({
    'et_markets', 'ndtv_profit', 'mint_rss', 'business_standard',
    'nse_rss', 'bse_rss', 'rbi', 'sebi', 'pib', 'investing_india', 'mcx',
})
MAX_AUTO_ARTICLES_PER_RUN = 200


def _canonical_url(value: object) -> str:
    text = str(value or '').strip()
    try:
        parsed = urlsplit(text)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.netloc:
            return ''
        query = [
            (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith('utm_') and key.lower() not in {'fbclid', 'gclid'}
        ]
        return urlunsplit((
            parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/') or '/',
            urlencode(query, doseq=True), '',
        ))
    except ValueError:
        return ''


def _article_id(provider_id: str, url: str, title: str, published_at: str) -> str:
    identity = f'{provider_id}\n{url or title.casefold()}\n{published_at[:19] if not url else ""}'
    return 'rss_' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:28]


def ingest_provider_articles(articles: list[dict[str, Any]] | None) -> dict[str, int | bool]:
    """Idempotently save fetched registry articles into the persistent My Feed DB."""
    stats: dict[str, int | bool] = {
        'ok': True, 'received': 0, 'inserted': 0, 'duplicates': 0,
        'skipped': 0, 'errors': 0,
    }
    saved_any = False

    batch = list(articles or [])
    stats['received'] = len(batch)
    if len(batch) > MAX_AUTO_ARTICLES_PER_RUN:
        stats['skipped'] = len(batch) - MAX_AUTO_ARTICLES_PER_RUN
    for article in batch[:MAX_AUTO_ARTICLES_PER_RUN]:
        if not isinstance(article, dict):
            stats['skipped'] = int(stats['skipped']) + 1
            continue
        provider_id = str(article.get('provider_id') or article.get('source_id') or '').strip().lower()
        title = re.sub(r'\s+', ' ', str(article.get('title') or article.get('headline') or '')).strip()
        url = _canonical_url(article.get('link') or article.get('url'))
        if provider_id not in SUPPORTED_PROVIDER_IDS or not title or not url:
            stats['skipped'] = int(stats['skipped']) + 1
            continue

        description = re.sub(r'\s+', ' ', str(article.get('description') or article.get('summary') or '')).strip()[:300]
        summary = title if not description or description.casefold() == title.casefold() else f'{title} — {description}'
        published_at = str(article.get('published_at') or article.get('published') or '').strip()
        feed_id = _article_id(provider_id, url, title, published_at)
        if get_item(feed_id):
            stats['duplicates'] = int(stats['duplicates']) + 1
            continue

        tickers = list(dict.fromkeys(
            str(t).upper() for t in (article.get('tickers') or article.get('symbols') or extract_tickers(summary)) if t
        ))
        classified = _classify_item({
            'cleaned_summary': summary,
            'items_found': 1,
            'tickers': tickers,
        })
        # Prefer the registry's deterministic feed classification when available.
        feed_type = str(article.get('feed_type') or 'news')
        record = {
            'feed_id': feed_id,
            'created_at': str(article.get('ingested_at') or datetime.now(timezone.utc).isoformat()),
            'source': AUTO_NEWS_SOURCE,
            'raw_market_text': summary,
            'cleaned_summary': summary,
            'detected_source_app': 'trusted_news_registry',
            'tickers': tickers or classified.get('tickers') or [],
            'sectors': classified.get('sectors') or [],
            'themes': classified.get('themes') or [],
            'event_type': classified.get('event_type') or feed_type,
            'sentiment': classified.get('sentiment') or 'neutral',
            'impact_score': classified.get('impact_score') or 0,
            'urgency': classified.get('urgency') or 'low',
            'suggested_action': classified.get('suggested_action') or 'NEWS ONLY',
            'confirmation_required': False,
            'status': 'active',
            'verification_status': 'UNVERIFIED',
            'source_name': str(article.get('source_name') or article.get('source') or provider_id),
            'payload': {
                'auto_ingested': True,
                'feed_type': feed_type,
                'provider_id': provider_id,
                'source_name': str(article.get('source_name') or article.get('source') or provider_id),
                'source_url': url,
                'published_at': published_at or None,
                'source_time_basis': str(article.get('source_time_basis') or 'MISSING'),
                'verification_status': 'UNVERIFIED',
                'verification_tier': article.get('verification_tier'),
                'verification_confidence': str(article.get('verification_confidence') or ''),
                'catalyst_eligible': False,
            },
        }
        try:
            insert_feed_item(record)
            stats['inserted'] = int(stats['inserted']) + 1
            saved_any = True
        except Exception:
            # A concurrent refresh can race on the deterministic primary key.
            if get_item(feed_id):
                stats['duplicates'] = int(stats['duplicates']) + 1
            else:
                stats['errors'] = int(stats['errors']) + 1

    if saved_any:
        try:
            from backend.my_feed.cache_invalidation import invalidate_myfeed_caches

            invalidate_myfeed_caches()
        except Exception:
            pass
    stats['ok'] = int(stats['errors']) == 0
    return stats
