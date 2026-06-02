"""
Real broker/app prediction collector (Stage 28 / 39).

Collects stock pick / watchlist signals from public RSS, cached news, TV intelligence,
manual inbox, and Angel One mentions in news.

Writes data/broker_app_collector_latest.json cache.
DB writes only when explicitly requested by caller (--write-broker-db).
External evidence stays separate from our own predictions.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import feedparser
import requests

from backend.analytics.broker_prediction_intelligence import (
    infer_direction_from_text,
    is_outcome_evidence,
    prepare_broker_pick_for_import,
)
from backend.collectors.external_evidence_classifier import (
    classify_external_item,
    load_universe,
)
from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

OUTPUT_FILE = DATA_DIR / 'broker_prediction_inbox.json'
CACHE_FILE = DATA_DIR / 'broker_app_collector_latest.json'
EXTERNAL_EVIDENCE_CACHE_FILE = DATA_DIR / 'external_evidence_latest.json'
DEFAULT_MANUAL_INBOX = DATA_DIR / 'broker_prediction_inbox.json'
COLLECTOR_VERSION = '3.2'

VALID_CLASSIFICATION_FILTERS = frozenset({
    'all',
    'broker_prediction_candidate',
    'stock_news_evidence',
    'market_context',
    'macro_context',
})

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; TradingCopilotBrokerCollector/2.0)',
    'Accept': 'application/rss+xml, application/xml, text/xml, */*',
}

BROKER_FEED_SOURCES: dict[str, str] = {
    'Moneycontrol Markets': 'https://www.moneycontrol.com/rss/marketreports.xml',
    'Moneycontrol Stocks': 'https://www.moneycontrol.com/rss/stocksinnews.xml',
    'ET Markets': 'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms',
    'ET Stocks': 'https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms',
    'Business Standard Markets': 'https://www.business-standard.com/rss/markets-106.rss',
    'LiveMint Markets': 'https://www.livemint.com/rss/markets',
    'LiveMint Companies': 'https://www.livemint.com/rss/companies',
    'NDTV Profit': 'https://feeds.feedburner.com/ndtvprofit-latest',
}

PICK_HEADLINE_RE = re.compile(
    r'\b('
    r'stocks?\s+to\s+watch|stock\s+watchlist|stocks?\s+in\s+focus|stock\s+picks?|top\s+picks?|'
    r'buy\s+call|sell\s+call|stock\s+recommendations?|broker(?:\'s)?\s+(?:buy|pick|call)|'
    r'shares?\s+to\s+buy|intraday\s+picks?|swing\s+picks?|add\s+to\s+portfolio|'
    r'must\s+buy|accumulate|outperform|upgrade\s+to\s+buy|downgrade\s+to\s+sell'
    r')\b',
    re.IGNORECASE,
)

REJECT_HEADLINE_RE = re.compile(
    r'\b('
    r'top\s+gainers?|top\s+losers?|eod\s+(?:gainers?|losers?|movers?)|'
    r'market\s+wrap|closing\s+bell|indices?\s+(?:close|end)|sensex\s+(?:ends|closes)|'
    r'nifty\s+(?:ends|closes)|most\s+active\s+stocks?|52[\s-]?week\s+(?:high|low)\s+list'
    r')\b',
    re.IGNORECASE,
)

ANGEL_HEADLINE_RE = re.compile(r'\bangel\s+one\b', re.IGNORECASE)

SOURCE_APP_MAP: dict[str, str] = {
    'moneycontrol': 'Moneycontrol',
    'economictimes': 'Economic Times',
    'business-standard': 'Business Standard',
    'livemint': 'LiveMint',
    'ndtvprofit': 'NDTV Profit',
    'feedburner': 'NDTV Profit',
}

COMPANY_TO_TICKER: dict[str, str] = {
    'reliance': 'RELIANCE',
    'tata consultancy': 'TCS',
    'tcs': 'TCS',
    'infosys': 'INFY',
    'wipro': 'WIPRO',
    'hdfc bank': 'HDFCBANK',
    'icici bank': 'ICICIBANK',
    'tata motors': 'TATAMOTORS',
    'tata steel': 'TATASTEEL',
    'tata power': 'TATAPOWER',
    'sun pharma': 'SUNPHARMA',
    'asian paints': 'ASIANPAINT',
    'bajaj finance': 'BAJFINANCE',
    'maruti suzuki': 'MARUTI',
    'bharti airtel': 'BHARTIARTL',
    'adani enterprises': 'ADANIENT',
    'jio financial': 'JIOFIN',
}

INDEX_SYMBOLS = frozenset({'NIFTY', 'NIFTY50', 'SENSEX', 'BANKNIFTY', 'FINNIFTY', 'NIFTY BANK'})
INDEX_ALIASES: dict[str, str] = {
    'NIFTY 50': 'NIFTY50',
    'NIFTY50': 'NIFTY50',
    'NIFTY': 'NIFTY50',
    'NIFTY BANK': 'BANKNIFTY',
    'BANK NIFTY': 'BANKNIFTY',
    'BANKNIFTY': 'BANKNIFTY',
    'SENSEX': 'SENSEX',
}
GENERIC_REJECT_TERMS = frozenset({
    'MARKET', 'INDIA', 'STOCK', 'STOCKS', 'SHARE', 'SHARES', 'EQUITY',
    'BUY', 'SELL', 'LIVE', 'TODAY',
})
ARTICLE_CONTAINER_KEYS = ('items', 'articles', 'news', 'headlines', 'data', 'results', 'feed', 'entries')
TV_CONTAINER_KEYS = ('videos', 'items')
TITLE_FIELD_KEYS = ('title', 'headline', 'name', 'summary', 'description', 'text')
BODY_FIELD_KEYS = ('description', 'summary', 'text', 'notes', 'content')
URL_FIELD_KEYS = ('url', 'link', 'source_url')
DATE_FIELD_KEYS = ('published_at', 'published', 'date', 'time', 'timestamp')
SOURCE_FIELD_KEYS = ('source', 'source_name', 'provider', 'channel', 'feed_name')
TICKER_FIELD_KEYS = ('ticker', 'symbol', 'tickers', 'symbols', 'tags', 'topics')
VALID_REJECTION_REASONS = frozenset({
    'no_ticker', 'low_market_relevance', 'duplicate', 'invalid_ticker',
    'empty_title', 'unsupported_shape', 'filtered_on_normalize',
})

EXPLICIT_BULLISH_RE = re.compile(
    r'\b(buy|accumulate|outperform|upgrade\s+to\s+buy|must\s+buy|add\s+to\s+portfolio|'
    r'target\s+price|upside|go\s+long|long\s+position)\b',
    re.IGNORECASE,
)
EXPLICIT_BEARISH_RE = re.compile(
    r'\b(sell|avoid|underperform|downgrade|downside|reduce|short\b|bearish)\b',
    re.IGNORECASE,
)

WATCH_TEXT_RE = re.compile(
    r'\b(stocks?\s+to\s+watch|stock\s+watchlist|stocks?\s+in\s+focus|in\s+focus)\b',
    re.IGNORECASE,
)

SOURCE_RELIABILITY_MAP: dict[str, str] = {
    'moneycontrol': 'medium',
    'economic times': 'medium',
    'et markets': 'medium',
    'business standard': 'medium',
    'livemint': 'medium',
    'ndtv profit': 'medium',
    'cnbc-tv18': 'medium',
    'cnbc tv18': 'medium',
    'zee business': 'medium',
    'business today': 'medium',
    'angel one': 'low',
    'manual': 'unknown',
    'tv intelligence': 'low',
}

VALID_SOURCES = frozenset({'all', 'news', 'tv', 'manual', 'angel'})


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_index_token(token: str) -> str:
    cleaned = re.sub(r'\s+', ' ', str(token or '').strip().upper())
    if cleaned in INDEX_ALIASES:
        return INDEX_ALIASES[cleaned]
    return cleaned.replace(' ', '')


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        val = row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ''


def _make_rejection(
    reason: str,
    *,
    title: str = '',
    source: str = '',
    collector_source: str = 'news',
    **extra: Any,
) -> dict[str, Any]:
    token = reason if reason in VALID_REJECTION_REASONS else 'unsupported_shape'
    row: dict[str, Any] = {
        'reason': token,
        'title': str(title or '')[:160],
        'source': str(source or '')[:80],
        'collector_source': collector_source,
    }
    row.update(extra)
    return row


def _append_rejection_sample(
    bucket: list[dict[str, Any]],
    rejection: dict[str, Any],
    *,
    sample_limit: int = 25,
) -> None:
    if len(bucket) < sample_limit:
        bucket.append(rejection)


def _record_rejection(
    bucket: list[dict[str, Any]],
    counts: dict[str, int],
    rejection: dict[str, Any],
    *,
    sample_limit: int = 25,
) -> None:
    reason = str(rejection.get('reason') or 'unsupported_shape')
    counts[reason] = counts.get(reason, 0) + 1
    _append_rejection_sample(bucket, rejection, sample_limit=sample_limit)


def _extract_article_records(
    data: Any,
    *,
    depth: int = 0,
    max_depth: int = 3,
    default_source: str = '',
) -> list[dict[str, Any]]:
    if depth > max_depth:
        return []
    if isinstance(data, list):
        rows: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                rows.append(item)
            elif isinstance(item, list):
                rows.extend(_extract_article_records(item, depth=depth + 1, max_depth=max_depth))
        return rows
    if not isinstance(data, dict):
        return []

    rows: list[dict[str, Any]] = []
    for key in ARTICLE_CONTAINER_KEYS:
        child = data.get(key)
        if isinstance(child, list):
            for item in child:
                if isinstance(item, dict):
                    source = _first_text(item, SOURCE_FIELD_KEYS) or default_source
                    merged = dict(item)
                    if source and not merged.get('source'):
                        merged['source'] = source
                    rows.append(merged)
                elif isinstance(item, list):
                    rows.extend(_extract_article_records(item, depth=depth + 1, max_depth=max_depth))
        elif isinstance(child, dict):
            rows.extend(_extract_article_records(child, depth=depth + 1, max_depth=max_depth, default_source=default_source))

    source_meta = data.get('source_meta')
    if isinstance(source_meta, dict):
        rows.extend(_extract_article_records(source_meta, depth=depth + 1, max_depth=max_depth, default_source=default_source))
    return rows


def _extract_tv_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in TV_CONTAINER_KEYS:
        child = data.get(key)
        if isinstance(child, list):
            rows.extend(row for row in child if isinstance(row, dict))
    return rows


def _article_fields_from_record(row: dict[str, Any], *, default_source: str = '') -> dict[str, Any]:
    title = _first_text(row, TITLE_FIELD_KEYS)
    body = _first_text(row, BODY_FIELD_KEYS)
    url = _first_text(row, URL_FIELD_KEYS)
    source = _first_text(row, SOURCE_FIELD_KEYS) or default_source
    published = _first_text(row, DATE_FIELD_KEYS)
    tags: list[str] = []
    for key in ('tags', 'topics', 'tickers', 'symbols'):
        val = row.get(key)
        if isinstance(val, list):
            tags.extend(str(v) for v in val if v is not None)
        elif val is not None and str(val).strip():
            tags.append(str(val))
    if tags:
        body = f'{body} {" ".join(tags)}'.strip()
    explicit_ticker = _first_text(row, ('ticker', 'symbol'))
    return {
        'title': title,
        'body': body,
        'url': url,
        'source': source,
        'published': published,
        'tags': tags,
        'explicit_ticker': explicit_ticker.upper() if explicit_ticker else '',
        'raw': row,
    }


def _tickers_from_record_fields(row: dict[str, Any], known_tickers: set[str]) -> tuple[list[str], str]:
    """Return tickers and extraction_method hint (title_match, topic_match, ticker_field)."""
    fields = _article_fields_from_record(row)
    title = fields['title']
    body = fields['body']
    explicit = fields['explicit_ticker']
    if explicit and _is_valid_ticker(explicit, known_tickers):
        return [explicit], 'ticker_field'

    title_tickers = extract_tickers_from_text(title, known_tickers, allow_index=True)
    if title_tickers:
        return title_tickers, 'title_match'

    body_tickers = extract_tickers_from_text(body, known_tickers, allow_index=True)
    if body_tickers:
        return body_tickers, 'title_match'

    topic_only: list[str] = []
    for tag in fields['tags']:
        token = _normalize_index_token(tag)
        if _is_valid_ticker(token, known_tickers):
            topic_only.append(token)
    if topic_only:
        return [], 'topic_match'
    return [], 'topic_match'


def _parse_entry_time(entry: dict) -> datetime | None:
    parsed = entry.get('published_parsed') or entry.get('updated_parsed')
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _clean_html(text: str) -> str:
    return re.sub(r'<[^>]+>', ' ', str(text or '')).strip()


def _load_known_tickers() -> set[str]:
    symbols: set[str] = set()
    universe_path = DATA_DIR / 'historical_ticker_universe.json'
    if universe_path.is_file():
        try:
            data = json.loads(universe_path.read_text(encoding='utf-8'))
            universe = data.get('tickers') or []
            if isinstance(universe, list):
                for row in universe:
                    if isinstance(row, dict):
                        token = _normalize_index_token(str(row.get('ticker') or ''))
                    else:
                        token = _normalize_index_token(str(row))
                    if len(token) >= 3:
                        symbols.add(token)
        except (OSError, json.JSONDecodeError):
            pass

    for path in (
        DATA_DIR / 'latest_market_data_memory_enriched.json',
        DATA_DIR / 'latest_market_data.json',
    ):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        prices = data.get('prices') or data.get('symbols') or {}
        if isinstance(prices, dict):
            for key in prices:
                token = _normalize_index_token(str(key))
                if len(token) >= 3:
                    symbols.add(token)

    if not symbols and universe_path.is_file():
        try:
            data = json.loads(universe_path.read_text(encoding='utf-8'))
            universe = data.get('tickers') or []
            if isinstance(universe, list):
                for row in universe:
                    if isinstance(row, dict):
                        token = _normalize_index_token(str(row.get('ticker') or ''))
                    else:
                        token = _normalize_index_token(str(row))
                    if len(token) >= 3:
                        symbols.add(token)
        except (OSError, json.JSONDecodeError):
            pass

    alias_path = DATA_DIR / 'company_alias_map.json'
    if alias_path.is_file():
        try:
            alias_data = json.loads(alias_path.read_text(encoding='utf-8'))
            for ticker in alias_data.get('tickers') or []:
                token = _normalize_index_token(str(ticker))
                if len(token) >= 3:
                    symbols.add(token)
            for ticker in (alias_data.get('aliases') or {}).values():
                token = _normalize_index_token(str(ticker))
                if len(token) >= 3:
                    symbols.add(token)
        except (OSError, json.JSONDecodeError):
            pass
    return symbols


def _is_valid_ticker(ticker: str, known_tickers: set[str] | None = None) -> bool:
    token = _normalize_index_token(ticker)
    if len(token) < 3 or len(token) > 20:
        return False
    if token in GENERIC_REJECT_TERMS and token not in INDEX_SYMBOLS:
        return False
    if known_tickers is not None and token not in known_tickers and token not in INDEX_SYMBOLS:
        return False
    if not re.match(r'^[A-Z0-9&.\-]+$', token):
        return False
    return True


def _dedupe_key(source: str, ticker: str, title: str, date_part: str) -> str:
    parts = '|'.join((
        str(source or '').strip().lower(),
        str(ticker or '').strip().upper(),
        str(title or '').strip().lower()[:160],
        str(date_part or '').strip()[:10],
    ))
    return hashlib.sha256(parts.encode('utf-8')).hexdigest()[:16]


def _load_dedupe_keys_from_cache() -> set[str]:
    keys: set[str] = set()
    if not CACHE_FILE.is_file():
        return keys
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return keys
    for item in cache.get('items') or []:
        if not isinstance(item, dict):
            continue
        raw = item.get('raw_payload') or {}
        if isinstance(raw, dict) and raw.get('dedupe_key'):
            keys.add(str(raw['dedupe_key']))
        title = str(item.get('headline') or item.get('title') or '')
        date_part = str(item.get('prediction_date') or item.get('published_at') or '')[:10]
        keys.add(_dedupe_key(
            str(item.get('broker_source') or ''),
            str(item.get('ticker') or ''),
            title,
            date_part,
        ))
    return keys


def _infer_source_reliability(source: str) -> str:
    lowered = str(source or '').strip().lower()
    for needle, reliability in SOURCE_RELIABILITY_MAP.items():
        if needle in lowered:
            return reliability
    return 'unknown'


def _map_source_type(collector_source: str, raw: dict[str, Any]) -> str:
    token = str(collector_source or '').strip().lower()
    if token == 'manual':
        return 'manual'
    if token == 'tv':
        return 'tv'
    if token == 'angel':
        return 'broker'
    raw_type = str(raw.get('source_type') or '').strip().lower()
    if raw_type in {'news', 'rss', 'tv', 'manual', 'broker'}:
        return raw_type
    if raw.get('feed_name') or raw.get('link'):
        return 'rss' if token == 'news' else 'news'
    return 'news'


def _infer_extraction_method(raw: dict[str, Any], ticker: str) -> str:
    hint = str(raw.get('extraction_method') or '').strip().lower()
    if hint in {'ticker_field', 'title_match', 'topic_match', 'manual'}:
        return hint
    for key in ('ticker', 'symbol'):
        val = raw.get(key)
        if val and _normalize_index_token(str(val)) == _normalize_index_token(str(ticker)):
            return 'ticker_field'
    title = str(raw.get('headline') or raw.get('title') or '')
    if title and extract_tickers_from_text(title, _load_known_tickers(), allow_index=True):
        if _normalize_index_token(str(ticker)) in extract_tickers_from_text(title, _load_known_tickers(), allow_index=True):
            return 'title_match'
    if raw.get('topics') or raw.get('tags'):
        return 'topic_match'
    if str(raw.get('collector_source') or '') == 'manual':
        return 'manual'
    return 'title_match'


def _infer_direction_confidence(
    text: str,
    stance: str | None,
    *,
    inferred_conf: float | None,
) -> str:
    body = str(text or '')
    if stance == 'WATCH':
        if re.search(r'\bstocks?\s+to\s+watch|watchlist|in\s+focus\b', body, re.IGNORECASE):
            return 'watch_only'
        return 'watch_only'
    if EXPLICIT_BULLISH_RE.search(body) and stance == 'BULLISH':
        return 'explicit'
    if EXPLICIT_BEARISH_RE.search(body) and stance == 'BEARISH':
        return 'explicit'
    if inferred_conf is not None:
        return 'inferred'
    return 'inferred' if stance else 'watch_only'


def _attach_source_quality(
    item: dict[str, Any],
    raw: dict[str, Any],
    *,
    text: str = '',
    inferred_conf: float | None = None,
) -> dict[str, Any]:
    broker_source = str(item.get('broker_source') or raw.get('broker_source') or 'unknown')
    collector_source = str(item.get('collector_source') or raw.get('collector_source') or 'news')
    ticker = str(item.get('ticker') or '')
    title = str(item.get('headline') or item.get('title') or '')
    date_part = str(item.get('prediction_date') or item.get('published_at') or '')[:10]
    stance = str(item.get('stance') or item.get('direction') or '')
    item['source'] = broker_source
    item['source_type'] = _map_source_type(collector_source, raw)
    item['source_reliability'] = _infer_source_reliability(broker_source)
    item['extraction_method'] = _infer_extraction_method(raw, ticker)
    item['direction_confidence'] = _infer_direction_confidence(
        text or title,
        stance,
        inferred_conf=inferred_conf,
    )
    dedupe = _dedupe_key(broker_source, ticker, title, date_part)
    merged_raw = dict(item.get('raw_payload') or raw)
    merged_raw['dedupe_key'] = dedupe
    item['raw_payload'] = merged_raw
    return item


def _infer_broker_source(feed_name: str, link: str = '') -> str:
    lowered = f'{feed_name} {link}'.lower()
    for needle, label in SOURCE_APP_MAP.items():
        if needle in lowered:
            return label
    return feed_name.split(' ', 1)[0].strip() or 'RSS'


def _infer_category(headline: str) -> str:
    text = headline.lower()
    if re.search(r'\bwatchlist|stocks?\s+to\s+watch|in\s+focus\b', text):
        return 'stocks_to_watch'
    if re.search(r'\bbuy\s+call|must\s+buy|accumulate|outperform\b', text):
        return 'buy_call'
    if re.search(r'\bsell\s+call|downgrade|underperform|avoid\b', text):
        return 'sell_call'
    if re.search(r'\btop\s+picks?|stock\s+picks?\b', text):
        return 'top_pick'
    return 'broker_pick'


def _headline_is_pick_candidate(headline: str, description: str = '') -> bool:
    text = f'{headline} {description}'.strip()
    if not text:
        return False
    if REJECT_HEADLINE_RE.search(text):
        return False
    return bool(PICK_HEADLINE_RE.search(text))


def extract_tickers_from_text(
    text: str,
    known_tickers: set[str],
    *,
    allow_index: bool = False,
) -> list[str]:
    if not text or not known_tickers:
        return []

    working = str(text)
    for alias, canonical in sorted(INDEX_ALIASES.items(), key=len, reverse=True):
        working = re.sub(rf'\b{re.escape(alias)}\b', canonical, working, flags=re.IGNORECASE)

    upper = re.sub(r'[^A-Z0-9&.\- ]+', ' ', working.upper())
    found: list[str] = []
    search_set = set(known_tickers)
    if allow_index:
        search_set |= INDEX_SYMBOLS

    for symbol in sorted(search_set, key=len, reverse=True):
        token = _normalize_index_token(symbol)
        if len(token) < 3:
            continue
        if token in GENERIC_REJECT_TERMS and token not in INDEX_SYMBOLS:
            continue
        if not allow_index and token in INDEX_SYMBOLS:
            continue
        if re.search(rf'\b{re.escape(token)}\b', upper):
            found.append(token)

    lowered = str(text).lower()
    for company_name, ticker in sorted(COMPANY_TO_TICKER.items(), key=lambda item: len(item[0]), reverse=True):
        mapped = _normalize_index_token(ticker)
        if mapped not in known_tickers and mapped not in INDEX_SYMBOLS:
            continue
        if mapped in GENERIC_REJECT_TERMS and mapped not in INDEX_SYMBOLS:
            continue
        if not allow_index and mapped in INDEX_SYMBOLS:
            continue
        if re.search(rf'\b{re.escape(company_name)}\b', lowered) and mapped not in found:
            found.append(mapped)

    ordered: list[str] = []
    seen: set[str] = set()
    for symbol in found:
        token = _normalize_index_token(symbol)
        if token not in seen and _is_valid_ticker(token, known_tickers if token not in INDEX_SYMBOLS else known_tickers | INDEX_SYMBOLS):
            seen.add(token)
            ordered.append(token)
    return ordered


def normalize_collected_item(raw: dict[str, Any], source: str) -> dict[str, Any] | None:
    """Normalize one raw collected row for cache/DB import."""
    return normalize_collected_item_with_reason(raw, source)[0]


def normalize_collected_item_with_reason(
    raw: dict[str, Any],
    source: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Normalize one raw collected row; returns (item, rejection_reason)."""
    if not isinstance(raw, dict):
        return None, 'unsupported_shape'
    if is_outcome_evidence(raw):
        return None, 'low_market_relevance'

    item = dict(raw)
    source_token = str(source or 'unknown').strip().lower()
    item['collector_source'] = source_token

    if source_token == 'tv':
        item.setdefault('broker_source', raw.get('channel') or raw.get('broker_source') or 'TV Intelligence')
    elif source_token == 'angel':
        item.setdefault('broker_source', 'Angel One')
    elif source_token == 'manual':
        item.setdefault('broker_source', raw.get('broker_source') or raw.get('source') or 'Manual')
    elif source_token == 'news':
        item.setdefault('broker_source', raw.get('broker_source') or raw.get('source') or 'News')

    known = _load_known_tickers()
    ticker = _normalize_index_token(str(item.get('ticker') or item.get('symbol') or ''))
    if not ticker:
        text_hint = ' '.join(str(item.get(key) or '') for key in ('headline', 'title', 'notes', 'description')).strip()
        extracted = extract_tickers_from_text(text_hint, known)
        extracted = [t for t in extracted if t not in INDEX_SYMBOLS]
        if extracted:
            ticker = extracted[0]
            item.setdefault('extraction_method', 'title_match')
    if ticker:
        item['ticker'] = ticker

    if not ticker:
        return None, 'no_ticker'
    if not _is_valid_ticker(ticker, known):
        return None, 'invalid_ticker'

    prepared = prepare_broker_pick_for_import(item, source_hint=item.get('broker_source'))
    if prepared is None:
        return None, 'filtered_on_normalize'

    text_hint = ' '.join(
        str(item.get(key) or '')
        for key in ('headline', 'title', 'notes', 'description')
    ).strip()
    inferred_conf = item.get('confidence')
    if inferred_conf is not None:
        try:
            inferred_conf = float(inferred_conf)
        except (TypeError, ValueError):
            inferred_conf = None

    normalized = {
        'broker_source': prepared.get('broker_source'),
        'ticker': prepared.get('ticker'),
        'stance': prepared.get('bullish_or_bearish'),
        'direction': prepared.get('bullish_or_bearish'),
        'target_type': prepared.get('target_type') or item.get('target_type'),
        'timeframe': prepared.get('timeframe') or item.get('timeframe') or '1w',
        'prediction_date': item.get('prediction_date') or _now_utc().strftime('%Y-%m-%d'),
        'published_at': item.get('published_at'),
        'confidence': prepared.get('confidence'),
        'headline': item.get('headline') or item.get('title'),
        'notes': item.get('notes') or item.get('description'),
        'url': item.get('url') or item.get('link'),
        'category': item.get('category') or item.get('target_type'),
        'prediction_id': prepared.get('prediction_id'),
        'collector_source': source_token,
        'raw_payload': prepared.get('raw_payload') or item.get('raw_payload') or {},
    }
    if item.get('classification'):
        normalized['classification'] = item.get('classification')
    if item.get('classification_reason'):
        normalized['classification_reason'] = item.get('classification_reason')
    if item.get('direction_reason'):
        normalized['direction_reason'] = item.get('direction_reason')
    if item.get('extraction_method'):
        normalized['extraction_method'] = item.get('extraction_method')
    return _attach_source_quality(
        normalized,
        {**item, **(normalized.get('raw_payload') or {})},
        text=text_hint,
        inferred_conf=inferred_conf,
    ), None


def _article_to_raw_items(
    *,
    feed_name: str,
    title: str,
    description: str,
    link: str,
    published_at: datetime | None,
    known_tickers: set[str],
    collector_source: str = 'news',
    extraction_method: str = 'title_match',
    explicit_ticker: str = '',
) -> list[dict[str, Any]]:
    headline = str(title or '').strip()
    body = _clean_html(description)
    combined = f'{headline} {body}'.strip()

    if not _headline_is_pick_candidate(headline, body):
        return []
    if REJECT_HEADLINE_RE.search(combined):
        return []

    tickers: list[str] = []
    method = extraction_method
    if explicit_ticker and _is_valid_ticker(explicit_ticker, known_tickers):
        tickers = [_normalize_index_token(explicit_ticker)]
        method = 'ticker_field'
    else:
        title_tickers = extract_tickers_from_text(headline, known_tickers)
        if title_tickers:
            tickers = title_tickers
            method = 'title_match'
        else:
            tickers = extract_tickers_from_text(combined, known_tickers)
            if tickers:
                method = 'title_match'
    if not tickers:
        return []

    broker_source = _infer_broker_source(feed_name, link)
    pub_iso = (published_at or _now_utc()).isoformat()
    prediction_date = (published_at or _now_utc()).strftime('%Y-%m-%d')
    category = _infer_category(headline)
    stance, inferred_conf = infer_direction_from_text(combined)
    if stance is None:
        if category == 'stocks_to_watch':
            stance = 'WATCH'
        elif category == 'sell_call' and EXPLICIT_BEARISH_RE.search(combined):
            stance = 'BEARISH'
            inferred_conf = 0.35
        elif EXPLICIT_BULLISH_RE.search(combined):
            stance = 'BULLISH'
            inferred_conf = 0.35
        elif category == 'sell_call':
            stance = 'BEARISH'
            inferred_conf = 0.35
        else:
            stance = 'WATCH'

    rows: list[dict[str, Any]] = []
    for ticker in tickers[:3]:
        row: dict[str, Any] = {
            'broker_source': broker_source,
            'ticker': ticker,
            'stance': stance,
            'direction': stance,
            'target_type': category,
            'timeframe': '1w',
            'prediction_date': prediction_date,
            'published_at': pub_iso,
            'headline': headline[:240],
            'notes': body[:400] if body else headline[:400],
            'url': link,
            'link': link,
            'category': category,
            'title': headline[:240],
            'description': body[:400],
            'source': feed_name,
            'extraction_method': method,
            'raw_payload': {
                'collector': 'broker_app_collector',
                'collector_source': collector_source,
                'feed_name': feed_name,
                'link': link,
                'published_at': pub_iso,
                'headline': headline,
                'description': body[:500],
                'category': category,
                'extraction_method': method,
            },
        }
        if inferred_conf is not None:
            row['confidence'] = inferred_conf
        rows.append(row)
    return rows


def evaluate_news_record(
    row: Any,
    *,
    feed_name: str,
    known_tickers: set[str],
    collector_source: str = 'news',
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not isinstance(row, dict):
        return [], _make_rejection('unsupported_shape', title='', source=feed_name, collector_source=collector_source)

    fields = _article_fields_from_record(row, default_source=feed_name)
    title = fields['title']
    body = fields['body']
    source = fields['source'] or feed_name
    if not title:
        return [], _make_rejection('empty_title', title='', source=source, collector_source=collector_source)

    combined = f'{title} {body}'.strip()
    if REJECT_HEADLINE_RE.search(combined):
        return [], _make_rejection('low_market_relevance', title=title, source=source, collector_source=collector_source)
    if not _headline_is_pick_candidate(title, body):
        return [], _make_rejection('low_market_relevance', title=title, source=source, collector_source=collector_source)

    tickers, method = _tickers_from_record_fields(row, known_tickers)
    if method == 'topic_match' and not tickers:
        return [], _make_rejection('no_ticker', title=title, source=source, collector_source=collector_source)
    if not tickers:
        return [], _make_rejection('no_ticker', title=title, source=source, collector_source=collector_source)

    stock_tickers = [t for t in tickers if t not in INDEX_SYMBOLS]
    if not stock_tickers:
        return [], _make_rejection('no_ticker', title=title, source=source, collector_source=collector_source)

    invalid = [t for t in stock_tickers if not _is_valid_ticker(t, known_tickers)]
    if invalid and not any(_is_valid_ticker(t, known_tickers) for t in stock_tickers):
        return [], _make_rejection(
            'invalid_ticker',
            title=title,
            source=source,
            collector_source=collector_source,
            ticker=invalid[0],
        )

    raw_rows = _article_to_raw_items(
        feed_name=source,
        title=title,
        description=body,
        link=fields['url'],
        published_at=None,
        known_tickers=known_tickers,
        collector_source=collector_source,
        extraction_method=method,
        explicit_ticker=fields['explicit_ticker'],
    )
    if not raw_rows:
        return [], _make_rejection('no_ticker', title=title, source=source, collector_source=collector_source)
    return raw_rows, None


def article_to_inbox_items(
    *,
    feed_name: str,
    title: str,
    description: str,
    link: str,
    published_at: datetime | None,
    known_tickers: set[str],
) -> tuple[list[dict[str, Any]], str | None]:
    raw_rows, rejection = evaluate_news_record(
        {
            'title': title,
            'description': description,
            'link': link,
            'source': feed_name,
        },
        feed_name=feed_name,
        known_tickers=known_tickers,
        collector_source='news',
    )
    if rejection:
        return [], str(rejection.get('reason'))

    items: list[dict[str, Any]] = []
    for raw in raw_rows:
        if published_at is not None:
            raw['published_at'] = published_at.isoformat()
            raw['prediction_date'] = published_at.strftime('%Y-%m-%d')
        normalized = normalize_collected_item(raw, 'news')
        if normalized:
            items.append(normalized)
    if not items:
        return [], 'filtered_on_normalize'
    return items, None


def fetch_feed_entries(
    feed_name: str,
    url: str,
    *,
    hours_back: int = 72,
    limit: int = 25,
    timeout: int = 15,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        if response.status_code != 200:
            return [], f'HTTP {response.status_code}'
        feed = feedparser.parse(response.content)
        cutoff = _now_utc() - timedelta(hours=max(1, int(hours_back)))
        entries: list[dict[str, Any]] = []
        for entry in (feed.entries or [])[: max(1, int(limit))]:
            pub = _parse_entry_time(entry)
            if pub and pub < cutoff:
                continue
            entries.append({
                'title': entry.get('title', ''),
                'description': entry.get('summary', '') or entry.get('description', ''),
                'link': entry.get('link', ''),
                'published_at': pub,
                'feed_name': feed_name,
            })
        return entries, None
    except requests.RequestException as exc:
        return [], str(exc)


def _collect_rss_raw(limit: int) -> list[dict[str, Any]]:
    known_tickers = _load_known_tickers()
    rows: list[dict[str, Any]] = []
    per_feed = max(5, min(int(limit), 25))
    for feed_name, url in BROKER_FEED_SOURCES.items():
        entries, _err = fetch_feed_entries(feed_name, url, limit=per_feed)
        for entry in entries:
            rows.extend(_article_to_raw_items(
                feed_name=feed_name,
                title=str(entry.get('title') or ''),
                description=str(entry.get('description') or ''),
                link=str(entry.get('link') or ''),
                published_at=entry.get('published_at'),
                known_tickers=known_tickers,
                collector_source='news',
            ))
            if len(rows) >= limit:
                return rows[:limit]
    return rows[:limit]


def _articles_from_json_payload(data: dict[str, Any], default_source: str) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    return _extract_article_records(data, default_source=default_source)


def _collect_news_with_rejections(
    *,
    limit: int,
    paths: tuple[Path, ...] | None = None,
    default_source: str = 'News Feed',
    collector_source: str = 'news',
    include_rss: bool = True,
    include_market_data: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    limit = max(1, int(limit))
    known_tickers = _load_known_tickers()
    rows: list[dict[str, Any]] = []
    rejected_sample: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = {}

    scan_paths = paths or (DATA_DIR / 'news_feed.json', DATA_DIR / 'live_news_feed.json')
    for path in scan_paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            _record_rejection(
                rejected_sample,
                rejection_counts,
                _make_rejection('unsupported_shape', title=str(path.name), source=default_source),
            )
            continue
        for article in _articles_from_json_payload(data if isinstance(data, dict) else {}, default_source):
            raw_rows, rejection = evaluate_news_record(
                article,
                feed_name=str(article.get('source') or default_source),
                known_tickers=known_tickers,
                collector_source=collector_source,
            )
            if raw_rows:
                rows.extend(raw_rows)
            elif rejection:
                _record_rejection(rejected_sample, rejection_counts, rejection)
            if len(rows) >= limit:
                return rows[:limit], rejected_sample, rejection_counts

    if include_market_data and len(rows) < limit:
        market_path = DATA_DIR / 'latest_market_data.json'
        if market_path.is_file():
            try:
                data = json.loads(market_path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                data = {}
            if isinstance(data, dict):
                for article in _articles_from_json_payload(data, 'Market Data'):
                    raw_rows, rejection = evaluate_news_record(
                        article,
                        feed_name=str(article.get('source') or 'Market Data'),
                        known_tickers=known_tickers,
                        collector_source=collector_source,
                    )
                    if raw_rows:
                        rows.extend(raw_rows)
                    elif rejection:
                        _record_rejection(rejected_sample, rejection_counts, rejection)
                    if len(rows) >= limit:
                        return rows[:limit], rejected_sample, rejection_counts

    if include_rss and len(rows) < limit:
        rss_rows = _collect_rss_raw(limit=max(0, limit - len(rows)))
        rows.extend(rss_rows)

    return rows[:limit], rejected_sample, rejection_counts


def collect_from_latest_market_data(limit: int = 50) -> list[dict[str, Any]]:
    """Collect pick candidates from latest_market_data.json news/source_meta."""
    rows, _, _ = _collect_news_with_rejections(
        limit=limit,
        paths=(),
        include_rss=False,
        include_market_data=True,
    )
    return rows


def collect_from_existing_news(limit: int = 50) -> list[dict[str, Any]]:
    """Collect broker pick candidates from cached news feeds and live RSS."""
    rows, _, _ = _collect_news_with_rejections(limit=limit)
    return rows


def evaluate_tv_record(
    video: Any,
    *,
    known_tickers: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not isinstance(video, dict):
        return [], _make_rejection('unsupported_shape', title='', source='TV Intelligence', collector_source='tv')

    title = str(video.get('title') or '').strip()
    description = str(video.get('description') or '')
    channel = str(video.get('channel') or 'TV Intelligence')
    topics = video.get('topics') or video.get('tags') or []
    topic_text = ' '.join(str(t) for t in topics) if isinstance(topics, list) else ''
    combined = f'{title} {description} {topic_text}'.strip()
    if not title:
        return [], _make_rejection('empty_title', title='', source=channel, collector_source='tv')

    symbols = video.get('symbols') or video.get('tickers') or []
    symbol_tickers = [
        _normalize_index_token(str(sym))
        for sym in (symbols if isinstance(symbols, list) else [symbols])
        if str(sym).strip()
    ]
    stock_symbols = [
        sym for sym in symbol_tickers
        if sym not in INDEX_SYMBOLS and _is_valid_ticker(sym, known_tickers)
    ]

    title_tickers = extract_tickers_from_text(title, known_tickers)
    body_tickers = extract_tickers_from_text(f'{description} {topic_text}', known_tickers)
    tickers = stock_symbols or title_tickers or body_tickers
    tickers = [t for t in tickers if t not in INDEX_SYMBOLS and _is_valid_ticker(t, known_tickers)]

    pick_like = _headline_is_pick_candidate(title, f'{description} {topic_text}')
    has_direction = bool(
        pick_like
        or stock_symbols
        or re.search(r'\b(stocks?\s+to\s+watch|buy|sell|accumulate|avoid|stock picks?)\b', combined, re.IGNORECASE)
    )
    if not tickers:
        if not has_direction:
            return [], _make_rejection('low_market_relevance', title=title, source=channel, collector_source='tv')
        return [], _make_rejection('no_ticker', title=title, source=channel, collector_source='tv')
    if not has_direction and not stock_symbols:
        return [], _make_rejection('low_market_relevance', title=title, source=channel, collector_source='tv')

    method = 'ticker_field' if stock_symbols else 'title_match'
    category = _infer_category(title)
    stance, inferred_conf = infer_direction_from_text(combined)
    if stance is None:
        if category == 'stocks_to_watch':
            stance = 'WATCH'
        elif EXPLICIT_BEARISH_RE.search(combined):
            stance = 'BEARISH'
            inferred_conf = 0.35
        elif EXPLICIT_BULLISH_RE.search(combined):
            stance = 'BULLISH'
            inferred_conf = 0.35
        else:
            stance = 'WATCH'

    pub_iso = str(video.get('published_at') or _now_utc().isoformat())
    rows: list[dict[str, Any]] = []
    for ticker in tickers[:3]:
        row = {
            'broker_source': channel,
            'ticker': ticker,
            'stance': stance,
            'direction': stance,
            'target_type': category,
            'timeframe': '1w',
            'prediction_date': pub_iso[:10],
            'published_at': pub_iso,
            'headline': title[:240],
            'notes': f'{description} {topic_text}'.strip()[:400],
            'url': str(video.get('url') or ''),
            'link': str(video.get('url') or ''),
            'category': category,
            'channel': video.get('channel'),
            'collector_source': 'tv',
            'extraction_method': method,
            'raw_payload': {
                'collector': 'broker_app_collector',
                'collector_source': 'tv',
                'video_id': video.get('video_id'),
                'channel': video.get('channel'),
                'url': video.get('url'),
                'topics': topics,
                'description': description[:500],
                'is_live': video.get('is_live'),
                'extraction_method': method,
            },
        }
        if inferred_conf is not None:
            row['confidence'] = inferred_conf
        rows.append(row)
    return rows, None


def collect_from_tv_intelligence(
    limit: int = 50,
    *,
    with_rejections: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Collect broker pick candidates from cached TV intelligence videos."""
    limit = max(1, int(limit))
    path = DATA_DIR / 'tv_intelligence.json'
    rejected_sample: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = {}
    if not path.is_file():
        if with_rejections:
            return [], rejected_sample, rejection_counts
        return []

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        if with_rejections:
            _record_rejection(
                rejected_sample,
                rejection_counts,
                _make_rejection('unsupported_shape', title='tv_intelligence.json', source='TV Intelligence', collector_source='tv'),
            )
            return [], rejected_sample, rejection_counts
        return []

    known_tickers = _load_known_tickers()
    rows: list[dict[str, Any]] = []
    for video in _extract_tv_records(data):
        raw_rows, rejection = evaluate_tv_record(video, known_tickers=known_tickers)
        if raw_rows:
            rows.extend(raw_rows)
        elif rejection:
            _record_rejection(rejected_sample, rejection_counts, rejection)
        if len(rows) >= limit:
            break
    trimmed = rows[:limit]
    if with_rejections:
        return trimmed, rejected_sample, rejection_counts
    return trimmed


def collect_from_manual_inbox(path: str = 'data/broker_prediction_inbox.json') -> list[dict[str, Any]]:
    """Collect raw items from a manual broker inbox JSON file."""
    inbox_path = Path(path)
    if not inbox_path.is_absolute():
        inbox_path = DATA_DIR.parent / path
    if not inbox_path.is_file():
        inbox_path = DATA_DIR / Path(path).name

    if not inbox_path.is_file():
        return []

    try:
        payload = json.loads(inbox_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []

    items = payload.get('items') if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            row = dict(item)
            row['collector_source'] = 'manual'
            rows.append(row)
    return rows


def collect_from_angel(limit: int = 50) -> list[dict[str, Any]]:
    """Collect Angel One mentions from cached news (no fake Angel API)."""
    limit = max(1, int(limit))
    known_tickers = _load_known_tickers()
    rows: list[dict[str, Any]] = []

    for path in (DATA_DIR / 'news_feed.json', DATA_DIR / 'live_news_feed.json'):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        for article in _articles_from_json_payload(data if isinstance(data, dict) else {}, 'News Feed'):
            title = str(article.get('title') or '')
            body = str(article.get('description') or article.get('summary') or '')
            combined = f'{title} {body}'
            if not ANGEL_HEADLINE_RE.search(combined):
                continue
            if not _headline_is_pick_candidate(title, body) and not PICK_HEADLINE_RE.search(combined):
                continue
            raw_rows, _rejection = evaluate_news_record(
                article,
                feed_name='Angel One News',
                known_tickers=known_tickers,
                collector_source='angel',
            )
            for raw in raw_rows:
                raw['broker_source'] = 'Angel One'
            rows.extend(raw_rows)
            if len(rows) >= limit:
                return rows[:limit]
    return rows[:limit]


def debug_broker_collector_extraction(
    *,
    source: str = 'all',
    limit: int = 50,
) -> dict[str, Any]:
    """Debug extraction from local sources with per-record outcomes."""
    source_token = str(source or 'all').strip().lower()
    limit = max(1, int(limit))
    known_tickers = _load_known_tickers()
    accepted: list[dict[str, Any]] = []
    rejected_sample: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = {}

    def _debug_line(kind: str, row: dict[str, Any]) -> None:
        print(
            f'[BROKER_COLLECTOR_DEBUG] kind={kind} reason={row.get("reason", "-")} '
            f'source={row.get("source", "-")} title={(row.get("title") or "-")[:80]} '
            f'ticker={row.get("ticker", "-")}'
        )

    if source_token in {'all', 'news'}:
        for path in (DATA_DIR / 'news_feed.json', DATA_DIR / 'live_news_feed.json'):
            if not path.is_file():
                print(f'[BROKER_COLLECTOR_DEBUG] missing_file={path.name}')
                continue
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                print(f'[BROKER_COLLECTOR_DEBUG] invalid_json={path.name}')
                continue
            records = _articles_from_json_payload(data if isinstance(data, dict) else {}, 'News Feed')
            print(f'[BROKER_COLLECTOR_DEBUG] file={path.name} records={len(records)}')
            for article in records[:limit]:
                raw_rows, rejection = evaluate_news_record(
                    article,
                    feed_name=str(article.get('source') or 'News Feed'),
                    known_tickers=known_tickers,
                    collector_source='news',
                )
                if raw_rows:
                    for raw in raw_rows:
                        accepted.append(raw)
                        _debug_line('accepted', {
                            'source': raw.get('broker_source'),
                            'title': raw.get('headline'),
                            'ticker': raw.get('ticker'),
                        })
                elif rejection:
                    _record_rejection(rejected_sample, rejection_counts, rejection)
                    _debug_line('rejected', rejection)

    if source_token in {'all', 'tv'}:
        tv_path = DATA_DIR / 'tv_intelligence.json'
        if tv_path.is_file():
            try:
                tv_data = json.loads(tv_path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                tv_data = {}
            tv_records = _extract_tv_records(tv_data)
            print(f'[BROKER_COLLECTOR_DEBUG] file=tv_intelligence.json records={len(tv_records)}')
            for video in tv_records[:limit]:
                raw_rows, rejection = evaluate_tv_record(video, known_tickers=known_tickers)
                if raw_rows:
                    for raw in raw_rows:
                        accepted.append(raw)
                        _debug_line('accepted', {
                            'source': raw.get('broker_source'),
                            'title': raw.get('headline'),
                            'ticker': raw.get('ticker'),
                        })
                elif rejection:
                    _record_rejection(rejected_sample, rejection_counts, rejection)
                    _debug_line('rejected', rejection)
        else:
            print('[BROKER_COLLECTOR_DEBUG] missing_file=tv_intelligence.json')

    if source_token in {'all', 'manual'}:
        manual_rows = collect_from_manual_inbox(str(DEFAULT_MANUAL_INBOX))
        print(f'[BROKER_COLLECTOR_DEBUG] file=broker_prediction_inbox.json records={len(manual_rows)}')
        for row in manual_rows[:limit]:
            normalized, reason = normalize_collected_item_with_reason(row, 'manual')
            if normalized:
                accepted.append(normalized)
                _debug_line('accepted', {
                    'source': normalized.get('broker_source'),
                    'title': normalized.get('headline'),
                    'ticker': normalized.get('ticker'),
                })
            else:
                rejection = _make_rejection(
                    reason or 'filtered_on_normalize',
                    title=str(row.get('headline') or row.get('title') or ''),
                    source=str(row.get('broker_source') or 'Manual'),
                    collector_source='manual',
                    ticker=str(row.get('ticker') or ''),
                )
                _record_rejection(rejected_sample, rejection_counts, rejection)
                _debug_line('rejected', rejection)

    print(
        f'[BROKER_COLLECTOR_DEBUG] accepted={len(accepted)} rejected={sum(rejection_counts.values())} '
        f'rejection_reasons={rejection_counts}'
    )
    print('BROKER_COLLECTOR_EXTRACTION_DEBUG_OK')
    return {
        'accepted': len(accepted),
        'rejected': sum(rejection_counts.values()),
        'rejection_reasons': rejection_counts,
        'rejected_items_sample': rejected_sample,
    }


def _summarize_items(
    items: list[dict[str, Any]],
    *,
    rejected: int = 0,
    warnings: list[str] | None = None,
    rejection_reasons: dict[str, int] | None = None,
) -> dict[str, Any]:
    direction_counts = {'bullish': 0, 'bearish': 0, 'watch': 0, 'neutral': 0}
    source_counts: dict[str, int] = {}
    sources: set[str] = set()
    tickers: set[str] = set()
    for item in items:
        stance = str(item.get('stance') or item.get('direction') or '').upper()
        if stance == 'BULLISH':
            direction_counts['bullish'] += 1
        elif stance == 'BEARISH':
            direction_counts['bearish'] += 1
        elif stance == 'WATCH':
            direction_counts['watch'] += 1
        else:
            direction_counts['neutral'] += 1
        src = str(item.get('broker_source') or item.get('source') or '')
        if src:
            sources.add(src)
            source_counts[src] = source_counts.get(src, 0) + 1
        if item.get('ticker'):
            tickers.add(str(item['ticker']).upper())
    summary = {
        'total': len(items),
        'normalized': len(items),
        'rejected': rejected,
        'sources': sorted(sources),
        'source_counts': source_counts,
        'tickers': sorted(tickers),
        'direction_counts': direction_counts,
        'warnings': warnings or [],
        # backward-compatible aliases
        'bullish': direction_counts['bullish'],
        'bearish': direction_counts['bearish'],
        'watch': direction_counts['watch'],
        'neutral': direction_counts['neutral'],
    }
    if rejection_reasons:
        summary['rejection_reasons'] = dict(rejection_reasons)
    return summary


def write_collector_cache(payload: dict[str, Any]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(CACHE_FILE, payload)
    return CACHE_FILE


def load_collector_cache() -> dict[str, Any]:
    if not CACHE_FILE.is_file():
        return {'ok': False, 'cache_exists': False, 'items': [], 'warnings': ['cache_missing']}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return {'ok': False, 'cache_exists': True, 'items': [], 'warnings': [str(exc)]}
    if isinstance(data, dict):
        data.setdefault('cache_exists', True)
        return data
    return {'ok': False, 'cache_exists': True, 'items': [], 'warnings': ['invalid_json']}


def import_normalized_to_db(items: list[dict[str, Any]], *, update_existing: bool = True) -> int:
    from backend.storage.market_memory_db import init_market_memory_db, upsert_broker_prediction

    if not init_market_memory_db():
        return 0

    written = 0
    seen_dedupe: set[str] = set()
    for item in items:
        prepared = prepare_broker_pick_for_import(item, source_hint=item.get('broker_source'))
        if prepared is None:
            continue
        dedupe_key = str(prepared.get('dedupe_key') or '')
        if dedupe_key and dedupe_key in seen_dedupe:
            continue
        if dedupe_key:
            seen_dedupe.add(dedupe_key)
        row_id = upsert_broker_prediction(prepared, update_existing=update_existing)
        if row_id is not None:
            written += 1
    return written


class BrokerWriteGateMismatch(RuntimeError):
    """Raised when broker DB writes exceed write-safe gate allowance."""


def enforce_broker_write_gate(
    *,
    written_to_db: int,
    review: dict[str, Any],
    db_items: list[dict[str, Any]],
) -> None:
    """Fail loudly if DB writes violate write gate constraints."""
    summary = review.get('summary') if isinstance(review.get('summary'), dict) else {}
    write_safe = int(summary.get('write_safe') or 0)
    review_only = int(summary.get('review_only') or 0)
    gate_duplicates = int(summary.get('duplicates') or 0)
    max_allowed = max(0, write_safe)

    if written_to_db > max_allowed:
        raise BrokerWriteGateMismatch(
            f'BROKER_WRITE_GATE_MISMATCH written_to_db={written_to_db} '
            f'write_safe={write_safe} gate_duplicates={gate_duplicates} '
            f'db_items={len(db_items)} review_only={review_only}',
        )

    for item in db_items:
        raw = item.get('raw_payload') if isinstance(item.get('raw_payload'), dict) else {}
        classification = str(item.get('classification') or raw.get('classification') or '')
        if classification != 'broker_prediction_candidate':
            raise BrokerWriteGateMismatch(
                f'BROKER_WRITE_GATE_MISMATCH non_candidate_written classification={classification}',
            )
        from backend.collectors.broker_db_write_gate import evaluate_broker_write_eligibility

        gate_row = {
            'ticker': item.get('ticker'),
            'title': item.get('headline') or item.get('title'),
            'source': item.get('broker_source') or item.get('source'),
            'direction': item.get('stance') or item.get('direction'),
            'direction_confidence': item.get('direction_confidence') or raw.get('direction_confidence'),
            'classification': classification,
            'classification_reason': item.get('classification_reason') or raw.get('classification_reason'),
            'raw_payload': raw,
            'collector_source': raw.get('collector_source'),
            'source_type': item.get('source_type') or raw.get('source_type'),
        }
        verdict = evaluate_broker_write_eligibility(gate_row)
        if verdict.get('eligibility') == 'review_only':
            raise BrokerWriteGateMismatch(
                f'BROKER_WRITE_GATE_MISMATCH review_only_written reason={verdict.get("reason")}',
            )
        if verdict.get('eligibility') != 'write_safe':
            raise BrokerWriteGateMismatch(
                f'BROKER_WRITE_GATE_MISMATCH unsafe_written eligibility={verdict.get("eligibility")}',
            )


def import_gated_broker_predictions(
    items: list[dict[str, Any]],
    *,
    update_existing: bool = True,
) -> tuple[int, dict[str, Any]]:
    """Gate, dedupe, write broker predictions; enforce write-safe limits."""
    from backend.collectors.broker_db_write_gate import gate_normalized_items_for_db

    db_items, review = gate_normalized_items_for_db(items)
    written_to_db = import_normalized_to_db(db_items, update_existing=update_existing) if db_items else 0
    enforce_broker_write_gate(written_to_db=written_to_db, review=review, db_items=db_items)
    return written_to_db, review


def get_external_source_coverage() -> dict[str, Any]:
    """External source coverage summary for API, daily pack, and inspect scripts."""
    cache = load_collector_cache()
    items = cache.get('items') if isinstance(cache.get('items'), list) else []
    summary = cache.get('summary') if isinstance(cache.get('summary'), dict) else _summarize_items(items)
    ext_cache = load_external_evidence_cache()
    ext_summary = ext_cache.get('summary') if isinstance(ext_cache.get('summary'), dict) else {}
    if not ext_summary and not ext_cache.get('items'):
        ext_cache = build_external_evidence_cache(limit=500)
        ext_summary = ext_cache.get('summary') or {}

    broker_db_picks = 0
    try:
        from backend.analytics.broker_prediction_intelligence import get_intelligence_stats

        stats = get_intelligence_stats()
        broker_db_picks = int(stats.get('broker_predictions') or 0)
    except Exception:
        broker_db_picks = 0

    source_list = summary.get('sources') or []
    if isinstance(summary.get('tickers'), list):
        unique_tickers = len(summary.get('tickers') or [])
        ticker_list = summary.get('tickers') or []
    else:
        ticker_list = sorted({
            str(item.get('ticker') or '').upper()
            for item in items
            if item.get('ticker')
        })
        unique_tickers = len(ticker_list)

    latest_sources = source_list[:10]
    warnings = list(cache.get('warnings') or summary.get('warnings') or [])
    if not items:
        warnings.append('no_collected_items')

    return {
        'ok': True,
        'cache_exists': bool(cache.get('cache_exists', CACHE_FILE.is_file())),
        'as_of': cache.get('as_of') or ext_cache.get('generated_at'),
        'collected_items': summary.get('total', len(items)),
        'normalized_items': summary.get('normalized', len(items)),
        'rejected_items': summary.get('rejected', cache.get('rejected', 0)),
        'source_count': len(source_list),
        'sources': source_list,
        'latest_sources': latest_sources,
        'unique_tickers': unique_tickers,
        'tickers': ticker_list[:50],
        'broker_db_pick_count': broker_db_picks,
        'source_counts': summary.get('source_counts') or {},
        'direction_counts': summary.get('direction_counts') or {},
        'fake_predictions': int(cache.get('fake_predictions') or ext_cache.get('fake_predictions') or 0),
        'channels_used': cache.get('channels_used') or [],
        'external_evidence': {
            'accepted': ext_summary.get('accepted', 0),
            'broker_prediction_candidate': ext_summary.get('broker_prediction_candidate', 0),
            'stock_news_evidence': ext_summary.get('stock_news_evidence', 0),
            'market_context': ext_summary.get('market_context', 0),
            'macro_context': ext_summary.get('macro_context', 0),
            'rejected': ext_summary.get('rejected', 0),
            'unique_tickers': ext_summary.get('unique_tickers', 0),
        },
        'warnings': warnings,
        'disclaimer': 'External evidence is separated from our final prediction.',
        'broker_write_review': _broker_write_review_summary(),
    }


def _broker_write_review_summary() -> dict[str, Any]:
    try:
        from backend.collectors.broker_db_write_gate import get_latest_broker_write_review

        review = get_latest_broker_write_review()
        summary = review.get('summary') if isinstance(review.get('summary'), dict) else {}
        return {
            'ok': review.get('ok', False),
            'generated_at': review.get('generated_at'),
            'write_safe': summary.get('write_safe', 0),
            'review_only': summary.get('review_only', 0),
            'rejected': summary.get('rejected', 0),
            'duplicates': summary.get('duplicates', 0),
            'disclaimer': 'Only write-safe items can enter broker prediction memory.',
        }
    except Exception:
        return {
            'ok': False,
            'write_safe': 0,
            'review_only': 0,
            'rejected': 0,
            'disclaimer': 'Only write-safe items can enter broker prediction memory.',
        }


def get_broker_app_collector_dashboard() -> dict[str, Any]:
    cache = load_collector_cache()
    items = cache.get('items') if isinstance(cache.get('items'), list) else []
    summary = cache.get('summary') if isinstance(cache.get('summary'), dict) else _summarize_items(items)
    coverage = get_external_source_coverage()
    external_evidence = get_external_evidence_dashboard()
    return {
        'ok': True,
        'cache_exists': bool(cache.get('cache_exists')),
        'cache_path': str(CACHE_FILE),
        'as_of': cache.get('as_of'),
        'source': cache.get('source'),
        'items': items[:50],
        'summary': summary,
        'external_source_coverage': coverage,
        'external_evidence': external_evidence,
        'broker_write_review': _broker_write_review_summary(),
        'disclaimer': 'Collected external evidence — not our prediction.',
    }


def _iter_raw_external_records(*, limit: int = 500) -> list[tuple[dict[str, Any], str]]:
    """Yield raw records from local news/TV/manual sources for classification."""
    records: list[tuple[dict[str, Any], str]] = []
    scan_limit = max(1, int(limit)) * 3

    for path, default_source in (
        (DATA_DIR / 'news_feed.json', 'News Feed'),
        (DATA_DIR / 'live_news_feed.json', 'Live News Feed'),
    ):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        for article in _articles_from_json_payload(data if isinstance(data, dict) else {}, default_source):
            records.append((article, 'news'))
            if len(records) >= scan_limit:
                return records

    tv_path = DATA_DIR / 'tv_intelligence.json'
    if tv_path.is_file():
        try:
            tv_data = json.loads(tv_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            tv_data = {}
        for video in _extract_tv_records(tv_data):
            records.append((video, 'tv'))
            if len(records) >= scan_limit:
                return records

    for row in collect_from_manual_inbox(str(DEFAULT_MANUAL_INBOX)):
        records.append((row, 'manual'))
        if len(records) >= scan_limit:
            return records

    return records


def _classified_to_broker_raw(classified: dict[str, Any], *, force_watch: bool = False) -> dict[str, Any] | None:
    """Convert classified external evidence to broker collector raw row."""
    token = str(classified.get('classification') or '')
    if token not in {'broker_prediction_candidate', 'stock_news_evidence'}:
        return None
    ticker = classified.get('ticker')
    if not ticker:
        return None

    title = str(classified.get('title') or '')[:240]
    raw = classified.get('raw_payload') if isinstance(classified.get('raw_payload'), dict) else {}
    source = str(classified.get('source') or raw.get('source') or raw.get('channel') or 'News')
    body = _first_text(raw, ('description', 'summary', 'text', 'notes'))
    collector_source = str(raw.get('collector_source') or 'news')

    direction = str(classified.get('direction') or 'WATCH').upper()
    if token == 'stock_news_evidence' or force_watch:
        if direction == 'BULLISH' and not EXPLICIT_BULLISH_RE.search(f'{title} {body}'):
            direction = 'WATCH'

    category = 'broker_pick'
    if WATCH_TEXT_RE.search(f'{title} {body}'):
        category = 'stocks_to_watch'
    elif EXPLICIT_BULLISH_RE.search(f'{title} {body}'):
        category = 'buy_call'
    elif EXPLICIT_BEARISH_RE.search(f'{title} {body}'):
        category = 'sell_call'

    return {
        'broker_source': source,
        'ticker': str(ticker).upper(),
        'stance': direction,
        'direction': direction,
        'target_type': category,
        'timeframe': '1w',
        'prediction_date': _first_text(raw, DATE_FIELD_KEYS)[:10] or _now_utc().strftime('%Y-%m-%d'),
        'published_at': _first_text(raw, DATE_FIELD_KEYS) or _now_utc().isoformat(),
        'headline': title,
        'notes': body[:400] if body else title[:400],
        'url': _first_text(raw, URL_FIELD_KEYS),
        'category': category,
        'collector_source': collector_source,
        'extraction_method': 'title_match',
        'classification': token,
        'classification_reason': classified.get('classification_reason'),
        'direction_reason': classified.get('direction_reason'),
        'matched_keywords': classified.get('matched_keywords') or [],
        'negative_override_applied': classified.get('negative_override_applied'),
        'raw_payload': {
            'collector': 'broker_app_collector',
            'collector_source': collector_source,
            'classification': token,
            'direction_confidence': classified.get('direction_confidence'),
            'evidence_strength': classified.get('evidence_strength'),
            'classification_reason': classified.get('classification_reason'),
            'direction_reason': classified.get('direction_reason'),
            'link': _first_text(raw, URL_FIELD_KEYS),
            'headline': title,
            'description': body[:500],
        },
    }


def build_external_evidence_cache(
    *,
    limit: int = 500,
    classification_filter: str = 'all',
) -> dict[str, Any]:
    """Classify all local external records; write external_evidence_latest.json."""
    filter_token = str(classification_filter or 'all').strip().lower()
    if filter_token not in VALID_CLASSIFICATION_FILTERS:
        filter_token = 'all'

    universe = load_universe()
    raw_records = _iter_raw_external_records(limit=limit)
    items: list[dict[str, Any]] = []
    rejection_reasons: dict[str, int] = {}
    classification_counts = {
        'broker_prediction_candidate': 0,
        'stock_news_evidence': 0,
        'market_context': 0,
        'macro_context': 0,
        'rejected': 0,
    }
    sources: set[str] = set()
    tickers: set[str] = set()
    seen_titles: set[str] = set()

    for raw, collector_source in raw_records:
        merged = dict(raw)
        if not merged.get('source'):
            merged['source'] = merged.get('channel') or merged.get('feed_name') or collector_source
        merged['collector_source'] = collector_source
        classified = classify_external_item(merged, universe)
        title_key = str(classified.get('title') or '').strip().lower()[:120]

        token = str(classified.get('classification') or 'reject')
        if token == 'reject':
            classification_counts['rejected'] += 1
            reason = str(classified.get('rejection_reason') or 'low_market_relevance')
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        elif token in classification_counts:
            classification_counts[token] += 1

        if classified.get('accepted'):
            src = str(classified.get('source') or '')
            if src:
                sources.add(src)
            if classified.get('ticker'):
                tickers.add(str(classified['ticker']).upper())

        if title_key and title_key in seen_titles:
            continue
        if title_key:
            seen_titles.add(title_key)

        if filter_token != 'all' and token != filter_token:
            continue
        items.append(classified)
        if len(items) >= limit:
            break

    accepted = sum(
        classification_counts[k]
        for k in ('broker_prediction_candidate', 'stock_news_evidence', 'market_context', 'macro_context')
    )
    payload: dict[str, Any] = {
        'ok': True,
        'generated_at': _now_utc().isoformat(),
        'classification_filter': filter_token,
        'items': items,
        'summary': {
            'total_raw': len(raw_records),
            'accepted': accepted,
            'broker_prediction_candidate': classification_counts['broker_prediction_candidate'],
            'stock_news_evidence': classification_counts['stock_news_evidence'],
            'market_context': classification_counts['market_context'],
            'macro_context': classification_counts['macro_context'],
            'rejected': classification_counts['rejected'],
            'unique_tickers': len(tickers),
            'sources': sorted(sources),
        },
        'rejection_reasons': rejection_reasons,
        'disclaimer': 'External evidence is separated from our final prediction.',
        'fake_predictions': 0,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(EXTERNAL_EVIDENCE_CACHE_FILE, payload)
    return payload


def load_external_evidence_cache() -> dict[str, Any]:
    if not EXTERNAL_EVIDENCE_CACHE_FILE.is_file():
        return {'ok': False, 'items': [], 'summary': {}}
    try:
        data = json.loads(EXTERNAL_EVIDENCE_CACHE_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {'ok': False, 'items': [], 'summary': {}}
    return data if isinstance(data, dict) else {'ok': False, 'items': [], 'summary': {}}


def get_external_evidence_dashboard() -> dict[str, Any]:
    cache = load_external_evidence_cache()
    if cache.get('ok') is not True and not cache.get('items'):
        cache = build_external_evidence_cache(limit=500)
    summary = cache.get('summary') if isinstance(cache.get('summary'), dict) else {}
    items = cache.get('items') if isinstance(cache.get('items'), list) else []
    by_class: dict[str, list[dict[str, Any]]] = {
        'broker_prediction_candidate': [],
        'stock_news_evidence': [],
        'market_context': [],
        'macro_context': [],
    }
    for row in items:
        if not isinstance(row, dict):
            continue
        token = str(row.get('classification') or '')
        if token in by_class and row.get('accepted'):
            by_class[token].append(row)

    return {
        'ok': True,
        'generated_at': cache.get('generated_at'),
        'summary': summary,
        'rejection_reasons': cache.get('rejection_reasons') or {},
        'broker_prediction_candidate': summary.get('broker_prediction_candidate', 0),
        'stock_news_evidence': summary.get('stock_news_evidence', 0),
        'market_context': summary.get('market_context', 0),
        'macro_context': summary.get('macro_context', 0),
        'broker_candidates': by_class['broker_prediction_candidate'][:15],
        'stock_news': by_class['stock_news_evidence'][:15],
        'market_context_items': by_class['market_context'][:15],
        'macro_context_items': by_class['macro_context'][:15],
        'disclaimer': cache.get('disclaimer') or 'External evidence is separated from our final prediction.',
        'fake_predictions': int(cache.get('fake_predictions') or 0),
    }


def collect_broker_app_predictions(
    *,
    limit: int = 50,
    dry_run: bool = False,
    source: str = 'all',
    verbose: bool = False,
    write_broker_db: bool = False,
    include_watch: bool = True,
    include_stock_news_as_watch: bool = False,
    exclude_tv: bool = False,
    exclude_news: bool = False,
    exclude_manual: bool = False,
    min_source_count: int = 0,
    classification: str = 'all',
    show_context: bool = False,
) -> dict[str, Any]:
    """Collect and normalize broker/app evidence; cache always written unless dry_run."""
    source_token = str(source or 'all').strip().lower()
    classification_filter = str(classification or 'all').strip().lower()
    if classification_filter not in VALID_CLASSIFICATION_FILTERS:
        classification_filter = 'all'
    if source_token not in VALID_SOURCES:
        return {
            'ok': False,
            'error': f'invalid source: {source}',
            'source': source_token,
            'collected': 0,
            'normalized': 0,
            'written_to_db': 0,
            'fake_predictions': 0,
        }

    limit = max(1, int(limit))
    raw_items: list[dict[str, Any]] = []
    channels_used: list[str] = []
    warnings: list[str] = []
    seen_dedupe = _load_dedupe_keys_from_cache()
    rejected_items_sample: list[dict[str, Any]] = []
    rejection_reasons: dict[str, int] = {}

    use_news = source_token in {'all', 'news'} and not exclude_news
    use_tv = source_token in {'all', 'tv'} and not exclude_tv
    use_manual = source_token in {'all', 'manual'} and not exclude_manual

    external_evidence = build_external_evidence_cache(
        limit=max(limit * 5, 200),
        classification_filter='all',
    )
    ext_summary = external_evidence.get('summary') if isinstance(external_evidence.get('summary'), dict) else {}
    for classified in external_evidence.get('items') or []:
        if not isinstance(classified, dict) or not classified.get('accepted'):
            continue
        raw_payload = classified.get('raw_payload') if isinstance(classified.get('raw_payload'), dict) else {}
        collector_source = str(raw_payload.get('collector_source') or 'news')
        if collector_source == 'news' and not use_news:
            continue
        if collector_source == 'tv' and not use_tv:
            continue
        if collector_source == 'manual' and not use_manual:
            continue
        if source_token not in {'all', collector_source}:
            continue

        token = str(classified.get('classification') or '')
        if token == 'broker_prediction_candidate':
            broker_raw = _classified_to_broker_raw(classified)
            if broker_raw:
                raw_items.append(broker_raw)
                if collector_source not in channels_used:
                    channels_used.append(collector_source)
        elif token == 'stock_news_evidence' and include_stock_news_as_watch:
            broker_raw = _classified_to_broker_raw(classified, force_watch=True)
            if broker_raw:
                raw_items.append(broker_raw)
                if collector_source not in channels_used:
                    channels_used.append(collector_source)

    if use_manual:
        manual_rows = collect_from_manual_inbox(str(DEFAULT_MANUAL_INBOX))
        for row in manual_rows[:limit]:
            row['collector_source'] = 'manual'
            raw_items.append(row)
        if manual_rows and 'manual' not in channels_used:
            channels_used.append('manual')

    if not (DATA_DIR / 'tv_intelligence.json').is_file() and use_tv:
        warnings.append('tv_intelligence_missing')

    collected = len(raw_items)
    normalized_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    rejected = 0

    for raw in raw_items:
        if source_token == 'all':
            channel = str(raw.get('collector_source') or 'news')
        else:
            channel = source_token
        normalized, norm_reason = normalize_collected_item_with_reason(raw, channel)
        if normalized is None:
            rejected += 1
            reason = norm_reason or 'filtered_on_normalize'
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
            _append_rejection_sample(
                rejected_items_sample,
                _make_rejection(
                    reason,
                    title=str(raw.get('headline') or raw.get('title') or ''),
                    source=str(raw.get('broker_source') or raw.get('source') or ''),
                    collector_source=channel,
                    ticker=str(raw.get('ticker') or ''),
                ),
            )
            continue

        stance = str(normalized.get('stance') or normalized.get('direction') or '').upper()
        if not include_watch and stance == 'WATCH':
            rejected += 1
            rejection_reasons['low_market_relevance'] = rejection_reasons.get('low_market_relevance', 0) + 1
            _append_rejection_sample(
                rejected_items_sample,
                _make_rejection(
                    'low_market_relevance',
                    title=str(normalized.get('headline') or ''),
                    source=str(normalized.get('broker_source') or ''),
                    collector_source=channel,
                    ticker=str(normalized.get('ticker') or ''),
                ),
            )
            continue

        raw_payload = normalized.get('raw_payload') or {}
        dedupe = str(raw_payload.get('dedupe_key') or '')
        if dedupe and dedupe in seen_dedupe:
            rejected += 1
            rejection_reasons['duplicate'] = rejection_reasons.get('duplicate', 0) + 1
            _append_rejection_sample(
                rejected_items_sample,
                _make_rejection(
                    'duplicate',
                    title=str(normalized.get('headline') or ''),
                    source=str(normalized.get('broker_source') or ''),
                    collector_source=channel,
                    ticker=str(normalized.get('ticker') or ''),
                ),
            )
            continue

        pred_id = str(normalized.get('prediction_id') or '')
        if pred_id and pred_id in seen_ids:
            rejected += 1
            rejection_reasons['duplicate'] = rejection_reasons.get('duplicate', 0) + 1
            _append_rejection_sample(
                rejected_items_sample,
                _make_rejection(
                    'duplicate',
                    title=str(normalized.get('headline') or ''),
                    source=str(normalized.get('broker_source') or ''),
                    collector_source=channel,
                    ticker=str(normalized.get('ticker') or ''),
                ),
            )
            continue
        if pred_id:
            seen_ids.add(pred_id)
        if dedupe:
            seen_dedupe.add(dedupe)
            seen_ids.add(dedupe)

        normalized_items.append(normalized)
        if len(normalized_items) >= limit:
            break

    rejected = sum(rejection_reasons.values())
    summary = _summarize_items(
        normalized_items,
        rejected=rejected,
        warnings=warnings,
        rejection_reasons=rejection_reasons,
    )
    if min_source_count > 0 and len(summary.get('sources') or []) < min_source_count:
        warnings.append(f'min_source_count_not_met:{min_source_count}')
        summary['warnings'] = warnings

    written_to_db = 0
    broker_write_review: dict[str, Any] = {}
    if write_broker_db and not dry_run:
        try:
            written_to_db, broker_write_review = import_gated_broker_predictions(
                normalized_items,
                update_existing=True,
            )
        except BrokerWriteGateMismatch as exc:
            return {
                'ok': False,
                'error': str(exc),
                'source': source_token,
                'collected': collected,
                'normalized': len(normalized_items),
                'written_to_db': 0,
                'fake_predictions': 0,
                'broker_write_review': broker_write_review,
            }

    payload: dict[str, Any] = {
        'ok': True,
        'source': source_token,
        'channels_used': channels_used,
        'as_of': _now_utc().isoformat(),
        'collector_version': COLLECTOR_VERSION,
        'collected': collected,
        'normalized': len(normalized_items),
        'rejected': rejected,
        'rejection_reasons': rejection_reasons,
        'rejected_items_sample': rejected_items_sample[:25],
        'written_to_db': written_to_db,
        'fake_predictions': 0,
        'dry_run': dry_run,
        'summary': summary,
        'items': normalized_items,
        'cache_path': str(CACHE_FILE),
        'external_evidence_path': str(EXTERNAL_EVIDENCE_CACHE_FILE),
        'external_evidence_summary': ext_summary,
        'classification_counts': {
            'broker_prediction_candidate': ext_summary.get('broker_prediction_candidate', 0),
            'stock_news_evidence': ext_summary.get('stock_news_evidence', 0),
            'market_context': ext_summary.get('market_context', 0),
            'macro_context': ext_summary.get('macro_context', 0),
            'rejected': ext_summary.get('rejected', 0),
        },
        'show_context': show_context,
        'include_stock_news_as_watch': include_stock_news_as_watch,
        'disclaimer': 'Collected external evidence — not our prediction.',
        'warnings': warnings,
        'broker_write_review': broker_write_review,
    }

    if verbose:
        print(
            f'[BROKER_COLLECTOR] source={source_token} collected={collected} '
            f'normalized={len(normalized_items)} rejected={rejected} '
            f'broker_candidates={ext_summary.get("broker_prediction_candidate", 0)} '
            f'stock_news={ext_summary.get("stock_news_evidence", 0)} '
            f'market_context={ext_summary.get("market_context", 0)} '
            f'macro_context={ext_summary.get("macro_context", 0)} '
            f'rejection_reasons={rejection_reasons} written_to_db={written_to_db}'
        )

    write_collector_cache(payload)
    if not dry_run:
        atomic_write_json(OUTPUT_FILE, {
            'source': 'broker_app_collector',
            'as_of': payload['as_of'],
            'items': normalized_items,
        })

    payload['external_source_coverage'] = get_external_source_coverage()
    payload['external_evidence'] = get_external_evidence_dashboard() if show_context else {
        'summary': ext_summary,
    }
    return payload


def run_broker_app_collector() -> dict[str, Any]:
    """Entry point for refresh-local-intelligence scope=brokers (cache only, no DB)."""
    return collect_broker_app_predictions(limit=50, dry_run=False, source='all', verbose=False, write_broker_db=False)


def load_broker_inbox() -> dict[str, Any]:
    if not OUTPUT_FILE.is_file():
        return {'ok': False, 'items': [], 'warnings': ['inbox_missing']}
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return {'ok': False, 'items': [], 'warnings': [str(exc)]}
    return data if isinstance(data, dict) else {'ok': False, 'items': [], 'warnings': ['invalid_json']}
