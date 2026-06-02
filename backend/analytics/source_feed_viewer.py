"""
Internal Source Feed Viewer — cached/local news and evidence only (Stage 44G).

Read-only aggregation from local JSON files. Never invents articles.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.utils.config import DATA_DIR

NEWS_FILES = (
    DATA_DIR / 'news_feed.json',
    DATA_DIR / 'live_news_feed.json',
)
EVIDENCE_FILE = DATA_DIR / 'external_evidence_latest.json'
BROKER_COLLECTOR_FILE = DATA_DIR / 'broker_app_collector_latest.json'
BROKER_INBOX_FILE = DATA_DIR / 'broker_prediction_inbox.json'
TV_INTELLIGENCE_FILE = DATA_DIR / 'tv_intelligence.json'
REDDIT_FILE = DATA_DIR / 'reddit_data.json'

ALL_FEED_PATHS = NEWS_FILES + (
    EVIDENCE_FILE,
    BROKER_COLLECTOR_FILE,
    BROKER_INBOX_FILE,
    TV_INTELLIGENCE_FILE,
    REDDIT_FILE,
)

SOURCE_LABELS: dict[str, str] = {
    'ET': 'Economic Times',
    'MC': 'Moneycontrol',
    'Mint': 'LiveMint',
    'NDTV': 'NDTV Profit',
    'CNBC': 'CNBC-TV18',
    'ET Now': 'ET Now',
    'NSE': 'NSE / India Market',
    'Reddit': 'Reddit',
    'Inshorts': 'Inshorts',
    'Angel': 'Angel One',
    'Zerodha': 'Zerodha',
    'Groww': 'Groww',
    'Upstox': 'Upstox',
    'IndMoney': 'IndMoney',
    'Portfolio': 'Yahoo Portfolio',
}

SOURCE_TYPES: dict[str, str] = {
    'ET': 'news',
    'MC': 'news',
    'Mint': 'news',
    'NDTV': 'news',
    'CNBC': 'news',
    'ET Now': 'news',
    'NSE': 'market',
    'Reddit': 'social',
    'Inshorts': 'social',
    'Angel': 'broker',
    'Zerodha': 'broker',
    'Groww': 'broker',
    'Upstox': 'broker',
    'IndMoney': 'broker',
    'Portfolio': 'broker',
}

# Raw feed/source name substrings → nav source key
_SOURCE_MATCHERS: list[tuple[str, tuple[str, ...]]] = [
    ('ET Now', ('et now',)),
    ('ET', (
        'economic times (markets alt)',
        'economic times markets alt',
        'economic times (markets)',
        'economic times markets',
        'et markets',
        'economic times',
        'economictimes',
    )),
    ('MC', ('moneycontrol', 'money control')),
    ('Mint', ('livemint', 'live mint', 'mint')),
    ('NDTV', ('ndtv profit', 'ndtv')),
    ('CNBC', ('cnbc-tv18', 'cnbc tv18', 'cnbc')),
    ('NSE', ('nse', 'nseindia', 'national stock exchange')),
    ('Reddit', ('reddit', 'r/indianstockmarket', 'r/indiainvestments')),
    ('Inshorts', ('inshorts',)),
    ('Angel', ('angel one', 'angelone')),
    ('Zerodha', ('zerodha', 'kite')),
    ('Groww', ('groww',)),
    ('Upstox', ('upstox',)),
    ('IndMoney', ('indmoney', 'ind money', 'indmoney')),
    ('Portfolio', ('yahoo finance portfolio', 'finance.yahoo.com/portfolios')),
]

_ALIAS_TO_KEY: dict[str, str] = {
    'ECONOMICTIMES': 'ET',
    'ECONOMICTIMESMARKETS': 'ET',
    'ECONOMICTIMESMARKETSALT': 'ET',
    'ETMARKETS': 'ET',
    'MC': 'MC',
    'MONEYCONTROL': 'MC',
    'LIVEMINT': 'Mint',
    'LIVEMINTCOMPANIES': 'Mint',
    'MINT': 'Mint',
    'NDTVPROFIT': 'NDTV',
    'NDTV': 'NDTV',
    'CNBCTV18': 'CNBC',
    'CNBC': 'CNBC',
    'ETNOW': 'ET Now',
    'NSE': 'NSE',
    'REDDIT': 'Reddit',
    'INSHORTS': 'Inshorts',
    'ANGEL': 'Angel',
    'ANGELONE': 'Angel',
    'ZERODHA': 'Zerodha',
    'GROWW': 'Groww',
    'UPSTOX': 'Upstox',
    'INDMONEY': 'IndMoney',
    'PORTFOLIO': 'Portfolio',
}

_EXACT_SOURCE_ALIASES: dict[str, str] = {
    'mc': 'MC',
    'et': 'ET',
    'mint': 'Mint',
    'nse': 'NSE',
    'cnbc': 'CNBC',
    'reddit': 'Reddit',
    'inshorts': 'Inshorts',
    'zerodha': 'Zerodha',
    'groww': 'Groww',
    'upstox': 'Upstox',
    'indmoney': 'IndMoney',
    'angel': 'Angel',
    'portfolio': 'Portfolio',
}

_CLASSIFICATION_ALIASES = {
    'broker_prediction_candidate': 'broker_candidates',
    'stock_news_evidence': 'stock_news',
    'market_context': 'market_context',
    'macro_context': 'macro_context',
    'reject': 'reject',
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(raw: object) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _normalize_text(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip().lower())


def normalize_source_name(source: str) -> str:
    """Map nav label / alias to canonical source key (ET, MC, …)."""
    raw = (source or '').strip()
    if not raw:
        return ''
    if raw in SOURCE_LABELS:
        return raw
    lower_map = {k.lower(): k for k in SOURCE_LABELS}
    if raw.lower() in lower_map:
        return lower_map[raw.lower()]
    compact = re.sub(r'[^a-zA-Z0-9]', '', raw).upper()
    if compact in _ALIAS_TO_KEY:
        return _ALIAS_TO_KEY[compact]
    if compact in SOURCE_LABELS:
        return compact
    lowered = _normalize_text(raw)
    if lowered in _EXACT_SOURCE_ALIASES:
        return _EXACT_SOURCE_ALIASES[lowered]
    for key, needles in _SOURCE_MATCHERS:
        for needle in needles:
            if needle in lowered:
                return key
    return raw


def _match_source_key(raw_source: str) -> Optional[str]:
    if not raw_source:
        return None
    lowered = _normalize_text(raw_source)
    if lowered in _EXACT_SOURCE_ALIASES:
        return _EXACT_SOURCE_ALIASES[lowered]
    compact = re.sub(r'[^a-zA-Z0-9]', '', raw_source).upper()
    if compact in _ALIAS_TO_KEY:
        return _ALIAS_TO_KEY[compact]
    for key, needles in _SOURCE_MATCHERS:
        for needle in needles:
            if needle in lowered:
                return key
    return None


def _item_dedupe_key(item: dict[str, Any]) -> str:
    title = _normalize_text(str(item.get('title') or ''))
    url = _normalize_text(str(item.get('url') or ''))
    return f'{title}|{url}'


def _format_classification(raw: object) -> str:
    text = str(raw or '').strip()
    if not text:
        return 'headline'
    return _CLASSIFICATION_ALIASES.get(text, text)


def _normalize_feed_item(
    *,
    title: str,
    source: str,
    url: str = '',
    classification: str = 'headline',
    ticker: object = None,
    direction: object = None,
    published_at: object = None,
) -> dict[str, Any]:
    return {
        'title': (title or '').strip(),
        'classification': _format_classification(classification),
        'ticker': ticker if ticker else None,
        'direction': str(direction or 'NEUTRAL').strip().upper() or 'NEUTRAL',
        'published_at': _parse_iso(published_at),
        'url': (url or '').strip(),
        'source': (source or '').strip(),
    }


def _ingest_news_articles(bucket: dict[str, list[dict[str, Any]]], data: dict[str, Any]) -> None:
    articles = data.get('articles') or []
    if not isinstance(articles, list):
        return
    for row in articles:
        if not isinstance(row, dict):
            continue
        raw_source = str(row.get('source') or '')
        key = _match_source_key(raw_source)
        if not key:
            continue
        item = _normalize_feed_item(
            title=str(row.get('title') or ''),
            source=raw_source,
            url=str(row.get('link') or row.get('url') or ''),
            classification='headline',
            ticker=row.get('ticker'),
            direction=row.get('sentiment_label') or row.get('direction') or 'NEUTRAL',
            published_at=row.get('published') or row.get('published_at'),
        )
        if item['title']:
            bucket.setdefault(key, []).append(item)


def _ingest_evidence(bucket: dict[str, list[dict[str, Any]]], data: dict[str, Any]) -> None:
    items = data.get('items') or []
    if not isinstance(items, list):
        return
    for row in items:
        if not isinstance(row, dict):
            continue
        raw_source = str(row.get('source') or '')
        key = _match_source_key(raw_source)
        if not key:
            continue
        raw_payload = row.get('raw_payload') if isinstance(row.get('raw_payload'), dict) else {}
        url = str(raw_payload.get('link') or raw_payload.get('url') or row.get('url') or '')
        item = _normalize_feed_item(
            title=str(row.get('title') or ''),
            source=raw_source,
            url=url,
            classification=str(row.get('classification') or 'headline'),
            ticker=row.get('ticker'),
            direction=row.get('direction') or 'NEUTRAL',
            published_at=raw_payload.get('published') or row.get('published_at'),
        )
        if item['title']:
            bucket.setdefault(key, []).append(item)


def _ingest_broker_collector(bucket: dict[str, list[dict[str, Any]]], data: dict[str, Any]) -> None:
    items = data.get('items') or []
    if not isinstance(items, list):
        return
    for row in items:
        if not isinstance(row, dict):
            continue
        raw_source = str(row.get('broker_source') or row.get('source') or '')
        key = _match_source_key(raw_source)
        if not key:
            continue
        item = _normalize_feed_item(
            title=str(row.get('headline') or row.get('title') or ''),
            source=raw_source,
            url=str(row.get('url') or ''),
            classification=str(row.get('classification') or 'broker_prediction_candidate'),
            ticker=row.get('ticker'),
            direction=row.get('direction') or row.get('stance') or 'NEUTRAL',
            published_at=row.get('published_at'),
        )
        if item['title']:
            bucket.setdefault(key, []).append(item)


def _ingest_tv_intelligence(bucket: dict[str, list[dict[str, Any]]], data: dict[str, Any]) -> None:
    videos = data.get('videos') or []
    if not isinstance(videos, list):
        return
    for row in videos:
        if not isinstance(row, dict):
            continue
        channel = str(row.get('channel') or '')
        url = str(row.get('url') or '')
        probe = f'{channel} {url}'.lower()
        key = _match_source_key(channel) or _match_source_key(url)
        if not key and 'et now' in probe:
            key = 'ET Now'
        if not key and ('cnbc' in probe or 'cnbc-tv18' in probe):
            key = 'CNBC'
        if not key:
            continue
        symbols = row.get('symbols') or []
        ticker = symbols[0] if isinstance(symbols, list) and symbols else None
        item = _normalize_feed_item(
            title=str(row.get('title') or ''),
            source=channel or key,
            url=url,
            classification='tv',
            ticker=ticker,
            direction='NEUTRAL',
            published_at=row.get('published_at') or data.get('generated_at'),
        )
        if item['title']:
            bucket.setdefault(key, []).append(item)


def _ingest_reddit(bucket: dict[str, list[dict[str, Any]]], data: dict[str, Any]) -> None:
    posts = data.get('posts') or data.get('top_posts') or []
    if not isinstance(posts, list):
        return
    for row in posts:
        if not isinstance(row, dict):
            continue
        tickers = row.get('tickers') or []
        ticker = tickers[0] if isinstance(tickers, list) and tickers else None
        item = _normalize_feed_item(
            title=str(row.get('title') or ''),
            source=f"Reddit / {row.get('subreddit') or 'social'}",
            url=str(row.get('url') or ''),
            classification='social',
            ticker=ticker,
            direction=row.get('sentiment') or 'NEUTRAL',
            published_at=data.get('last_updated'),
        )
        if item['title']:
            bucket.setdefault('Reddit', []).append(item)


def _dedupe_and_sort(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = _item_dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda r: str(r.get('published_at') or ''), reverse=True)
    return unique[:limit]


def _count_buckets(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        'total': len(items),
        'stock_news': 0,
        'market_context': 0,
        'macro_context': 0,
        'broker_candidates': 0,
    }
    for item in items:
        cls = str(item.get('classification') or '')
        if cls in ('stock_news', 'stock_news_evidence'):
            counts['stock_news'] += 1
        elif cls == 'market_context':
            counts['market_context'] += 1
        elif cls == 'macro_context':
            counts['macro_context'] += 1
        elif cls in ('broker_candidates', 'broker_prediction_candidate'):
            counts['broker_candidates'] += 1
    return counts


def _latest_timestamp(paths: tuple[Path, ...], payloads: list[dict[str, Any]]) -> str:
    best: Optional[datetime] = None
    for payload in payloads:
        for key in ('last_updated', 'generated_at', 'as_of'):
            raw = payload.get(key)
            if not raw:
                continue
            try:
                text = str(raw).strip()
                if text.endswith('Z'):
                    text = text[:-1] + '+00:00'
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if best is None or dt > best:
                    best = dt
            except (TypeError, ValueError):
                continue
    for path in paths:
        if path.is_file():
            try:
                dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if best is None or dt > best:
                    best = dt
            except OSError:
                pass
    return best.isoformat() if best else _now_iso()


def group_cached_news_by_source() -> dict[str, list[dict[str, Any]]]:
    """Aggregate all cached items keyed by nav source (ET, MC, …)."""
    bucket: dict[str, list[dict[str, Any]]] = {}
    payloads: list[dict[str, Any]] = []

    for path in NEWS_FILES:
        data = _load_json(path)
        if data:
            payloads.append(data)
            _ingest_news_articles(bucket, data)

    evidence = _load_json(EVIDENCE_FILE)
    if evidence:
        payloads.append(evidence)
        _ingest_evidence(bucket, evidence)

    broker = _load_json(BROKER_COLLECTOR_FILE)
    if broker:
        payloads.append(broker)
        _ingest_broker_collector(bucket, broker)

    inbox = _load_json(BROKER_INBOX_FILE)
    if inbox:
        payloads.append(inbox)
        _ingest_broker_collector(bucket, inbox)

    tv = _load_json(TV_INTELLIGENCE_FILE)
    if tv:
        payloads.append(tv)
        _ingest_tv_intelligence(bucket, tv)

    reddit = _load_json(REDDIT_FILE)
    if reddit:
        payloads.append(reddit)
        _ingest_reddit(bucket, reddit)

    for key in list(bucket.keys()):
        bucket[key] = _dedupe_and_sort(bucket[key], limit=500)

    return bucket


def get_source_feed(source: str, limit: int = 100) -> dict[str, Any]:
    """Return cached feed for one nav source key."""
    key = normalize_source_name(source)
    if not key:
        return {
            'ok': False,
            'error': 'invalid_source',
            'source': source,
            'items': [],
            'warnings': ['invalid_source'],
        }

    grouped = group_cached_news_by_source()
    items = _dedupe_and_sort(grouped.get(key, []), limit=max(1, int(limit)))

    paths = ALL_FEED_PATHS
    payloads = [_load_json(p) for p in paths if _load_json(p)]
    last_updated = _latest_timestamp(paths, payloads)

    warnings: list[str] = []
    if not items:
        warnings.append('no_cached_items')

    return {
        'ok': True,
        'source': key,
        'source_label': SOURCE_LABELS.get(key, key),
        'source_type': SOURCE_TYPES.get(key, 'news'),
        'items': items,
        'counts': _count_buckets(items),
        'last_updated': last_updated,
        'warnings': warnings,
    }
