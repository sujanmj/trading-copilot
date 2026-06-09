"""
AstraEdge Broker Intelligence — Stage 48Q.

Full broker consensus, upgrades/downgrades, target prices, freshness.
Research-only — watch/confirm stances, never buy now or guaranteed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
STAGE = '48R'
ENGINE_NAME = 'Broker Intelligence'
CACHE_FILE = get_data_path('broker_intelligence_cache.json')
COLLECTOR_CACHE = get_data_path('broker_app_collector_latest.json')
INBOX_FILE = get_data_path('broker_prediction_inbox.json')
CONSENSUS_INBOX = get_data_path('broker_consensus_inbox.json')
MISSING_MESSAGE = 'Broker cache unavailable. Tap Refresh Brokers.'

FORBIDDEN_WORDS = ('buy now', 'guaranteed', 'sure shot', 'sell now', 'invest now')
ALLOWED_SUGGESTED_ACTIONS = (
    'Watch for Confirmation',
    'Research Only',
    'Avoid-Risk',
    'Wait',
)

POSITIVE_RATING_RE = re.compile(
    r'\b(buy|add|accumulate|overweight|outperform|strong\s+buy|positive)\b',
    re.IGNORECASE,
)
NEUTRAL_RATING_RE = re.compile(
    r'\b(hold|neutral|equal[\s-]?weight|market[\s-]?perform|maintain)\b',
    re.IGNORECASE,
)
NEGATIVE_RATING_RE = re.compile(
    r'\b(sell|reduce|underperform|underweight|negative|avoid)\b',
    re.IGNORECASE,
)
UPGRADE_RE = re.compile(r'\b(upgrade[ds]?|raised?\s+to\s+buy|moved?\s+to\s+buy)\b', re.IGNORECASE)
DOWNGRADE_RE = re.compile(r'\b(downgrade[ds]?|cut\s+to\s+sell|moved?\s+to\s+sell)\b', re.IGNORECASE)
TARGET_RAISE_RE = re.compile(
    r'\b(target\s+(?:raised|hiked|upped|increased)|raises?\s+target|target\s+price\s+raised|'
    r'price\s+target\s+raised|hikes?\s+target)\b',
    re.IGNORECASE,
)
TARGET_CUT_RE = re.compile(
    r'\b(target\s+(?:cut|lowered|reduced|slashed)|cuts?\s+target|target\s+price\s+cut|'
    r'price\s+target\s+cut|lowers?\s+target)\b',
    re.IGNORECASE,
)
TARGET_PRICE_RE = re.compile(
    r'(?:target\s+price|price\s+target|target|tp)\s*(?:to|of|at|:)?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)',
    re.IGNORECASE,
)
PREV_TARGET_RE = re.compile(
    r'(?:from|earlier|previous)\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)',
    re.IGNORECASE,
)
CRYPTO_ONLY_RE = re.compile(r'\b(bitcoin|ethereum|crypto|btc|eth)\b', re.IGNORECASE)
US_ONLY_RE = re.compile(
    r'\b(nasdaq|dow\s+jones|s\s*&\s*p|nyse|wall\s+street|fed\s+rate)\b',
    re.IGNORECASE,
)
INDIA_CONTEXT_RE = re.compile(
    r'\b(nse|bse|nifty|sensex|india|rupee|sebi|rbi|mumbai)\b',
    re.IGNORECASE,
)
GENERIC_NEWS_RE = re.compile(
    r'\b(market\s+wrap|closing\s+bell|indices?\s+(?:close|end)|most\s+active|'
    r'top\s+gainers?|top\s+losers?|eod\s+movers?)\b',
    re.IGNORECASE,
)
BROKER_HOUSE_RE = re.compile(
    r'\b(motilal|oswal|icici\s+securities|hdfc\s+sec|kotak|jefferies|clsa|'
    r'goldman|morgan\s+stanley|jpmorgan|citi|bank\s+of\s+america|ubs|'
    r'nomura|macquarie|axis\s+cap|edelweiss|prabhudas|sharekhan|angel\s+one)\b',
    re.IGNORECASE,
)
WATCHLIST_MENTION_RE = re.compile(
    r'\b(stocks?\s+to\s+watch|shares?\s+to\s+watch|key\s+stocks?|buzzing\s+stocks?|'
    r'top\s+gainers?|top\s+losers?|market\s+movers?|in\s+focus)\b',
    re.IGNORECASE,
)
TRUE_BROKER_SIGNAL_RE = re.compile(
    r'\b(brokerage|analyst|rating|target\s+price|upgrade|downgrade|'
    r'buy|add|hold|sell|reduce|overweight|outperform|underperform|'
    r'initiated\s+coverage|maintained\s+rating|reiterate)\b',
    re.IGNORECASE,
)
ANALYST_RE = re.compile(r'\banalyst\b', re.IGNORECASE)

EVIDENCE_TYPES = (
    'broker_rating',
    'analyst_rating',
    'target_price_change',
    'upgrade_downgrade',
    'market_watchlist_mention',
    'news_mention',
    'external_context',
)
CONSENSUS_EVIDENCE_TYPES = frozenset({
    'broker_rating',
    'analyst_rating',
    'target_price_change',
    'upgrade_downgrade',
})


def _log(msg: str) -> None:
    print(f'[BROKER_INTEL] {msg}', flush=True)


def _now_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


def _sanitize_text(text: str) -> str:
    out = str(text or '')
    for word in FORBIDDEN_WORDS:
        out = re.sub(re.escape(word), 'watch', out, flags=re.IGNORECASE)
    return out


def _normalize_ticker(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper().replace(' ', '')
    return text or None


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def _parse_date(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.fromisoformat(text.replace('Z', '+00:00')) if 'T' in text else datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)
            return dt.astimezone(IST)
        except ValueError:
            continue
    return None


def _evidence_timestamp(row: dict[str, Any]) -> datetime | None:
    for key in ('published_at', 'extracted_at', 'prediction_date', 'date', 'generated_at'):
        parsed = _parse_date(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _freshness_from_timestamp(ts: datetime | None) -> str:
    if ts is None:
        return 'unknown'
    age = datetime.now(IST) - ts
    if age <= timedelta(hours=24):
        return 'fresh'
    if age <= timedelta(days=7):
        return 'aging'
    return 'stale'


def _truncate_headline(text: str, max_len: int = 110) -> str:
    raw = ' '.join(str(text or '').split())
    if len(raw) <= max_len:
        return raw
    trimmed = raw[: max_len - 1].rsplit(' ', 1)[0]
    if len(trimmed) < max_len // 2:
        trimmed = raw[: max_len - 1]
    return trimmed.rstrip(' ,;:') + '…'


def _combined_text(item: dict[str, Any]) -> str:
    parts = [
        item.get('headline'),
        item.get('title'),
        item.get('notes'),
        item.get('description'),
        item.get('summary'),
    ]
    raw = item.get('raw_payload')
    if isinstance(raw, dict):
        parts.extend([raw.get('headline'), raw.get('description'), raw.get('notes')])
    return ' '.join(str(p) for p in parts if p).strip()


def _load_json_file(path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _load_cache() -> dict[str, Any]:
    raw = _load_json_file(CACHE_FILE)
    if not raw:
        return {}
    if raw.get('generated_at') or raw.get('consensus_by_ticker') is not None:
        normalized = dict(raw)
        normalized.setdefault('ok', True)
        return _enrich_cache_buckets(normalized)
    return raw


def verify_broker_cache_write() -> dict[str, Any]:
    """Verify broker_intelligence_cache.json exists and has required fields."""
    if not CACHE_FILE.is_file():
        return {'ok': False, 'error': 'cache_file_missing'}
    cached = _load_json_file(CACHE_FILE)
    if not cached:
        return {'ok': False, 'error': 'cache_empty_or_invalid'}
    generated_at = cached.get('generated_at')
    if not generated_at:
        return {'ok': False, 'error': 'missing_generated_at'}
    evidence_items = cached.get('evidence_items') or []
    consensus = cached.get('consensus_by_ticker') or {}
    return {
        'ok': True,
        'generated_at': generated_at,
        'evidence_count': len(evidence_items),
        'ticker_count': len(consensus),
        'tracked_tickers': cached.get('tracked_tickers') or len(consensus),
    }


def _cache_exists_on_disk() -> bool:
    cached = _load_cache()
    return bool(cached.get('generated_at') or cached.get('ok'))


def _save_cache(payload: dict[str, Any]) -> None:
    payload['stage'] = STAGE
    payload['engine'] = ENGINE_NAME
    atomic_write_json(CACHE_FILE, payload)


def _file_age_hours(path) -> Optional[float]:
    try:
        if not path.is_file():
            return None
        mtime = datetime.fromtimestamp(path.stat().st_mtime, IST)
        return (datetime.now(IST) - mtime).total_seconds() / 3600.0
    except OSError:
        return None


def should_reject_item(item: dict[str, Any]) -> tuple[bool, str | None]:
    text = _combined_text(item)
    if not text.strip():
        return True, 'empty_text'
    if GENERIC_NEWS_RE.search(text):
        if not (WATCHLIST_MENTION_RE.search(text) and not TRUE_BROKER_SIGNAL_RE.search(text)):
            return True, 'generic_news'
    if CRYPTO_ONLY_RE.search(text) and not INDIA_CONTEXT_RE.search(text):
        return True, 'crypto_only'
    if US_ONLY_RE.search(text) and not INDIA_CONTEXT_RE.search(text):
        return True, 'us_only_no_india'
    ticker = _normalize_ticker(item.get('ticker') or item.get('symbol'))
    if not ticker:
        return True, 'no_ticker'
    rating = classify_rating(item)
    pub = _parse_date(item.get('published_at') or item.get('prediction_date') or item.get('date'))
    if pub and (datetime.now(IST) - pub) > timedelta(days=14) and rating == 'unknown':
        return True, 'stale_without_label'
    return False, None


def extract_broker_house(text: str) -> str | None:
    match = BROKER_HOUSE_RE.search(text or '')
    if match:
        return match.group(0).strip().title()
    return None


def detect_action(text: str) -> str | None:
    body = str(text or '')
    if UPGRADE_RE.search(body):
        return 'upgrade'
    if DOWNGRADE_RE.search(body):
        return 'downgrade'
    if TARGET_RAISE_RE.search(body):
        return 'target_raised'
    if TARGET_CUT_RE.search(body):
        return 'target_cut'
    if POSITIVE_RATING_RE.search(body):
        return 'positive_rating'
    if NEGATIVE_RATING_RE.search(body):
        return 'negative_rating'
    if NEUTRAL_RATING_RE.search(body):
        return 'neutral_rating'
    return None


def extract_target_prices(text: str) -> tuple[float | None, float | None]:
    body = str(text or '')
    current = None
    previous = None
    match = TARGET_PRICE_RE.search(body)
    if match:
        current = _parse_float(match.group(1))
    prev = PREV_TARGET_RE.search(body)
    if prev:
        previous = _parse_float(prev.group(1))
    return current, previous


def classify_rating(item: dict[str, Any]) -> str:
    text = _combined_text(item)
    stance = str(
        item.get('stance') or item.get('direction') or item.get('bullish_or_bearish') or ''
    ).strip().upper()
    if stance in {'BULLISH', 'BUY', 'ACCUMULATE', 'OUTPERFORM', 'OVERWEIGHT', 'LONG'}:
        return 'positive'
    if stance in {'BEARISH', 'SELL', 'REDUCE', 'UNDERPERFORM', 'UNDERWEIGHT', 'SHORT'}:
        return 'negative'
    if stance in {'NEUTRAL', 'HOLD', 'EQUAL_WEIGHT'}:
        return 'neutral'
    if stance == 'WATCH':
        return 'neutral'
    if POSITIVE_RATING_RE.search(text) or TARGET_RAISE_RE.search(text) or UPGRADE_RE.search(text):
        return 'positive'
    if NEGATIVE_RATING_RE.search(text) or TARGET_CUT_RE.search(text) or DOWNGRADE_RE.search(text):
        return 'negative'
    if NEUTRAL_RATING_RE.search(text):
        return 'neutral'
    return 'unknown'


    return 'unknown'


def classify_evidence_type(
    raw: dict[str, Any],
    *,
    text: str | None = None,
    action: str | None = None,
    rating: str | None = None,
    target_price: float | None = None,
) -> str:
    """Classify broker evidence — only true ratings count toward consensus."""
    body = str(text if text is not None else _combined_text(raw))
    act = action if action is not None else detect_action(body)
    rate = rating if rating is not None else classify_rating(raw)
    tp = target_price
    if tp is None and raw.get('target_price') is not None:
        tp = _parse_float(raw.get('target_price'))
    if tp is None:
        tp, _ = extract_target_prices(body)

    has_true_broker = bool(TRUE_BROKER_SIGNAL_RE.search(body) or BROKER_HOUSE_RE.search(body))
    has_watchlist = bool(WATCHLIST_MENTION_RE.search(body))

    if act in {'upgrade', 'downgrade'} and has_true_broker:
        return 'upgrade_downgrade'
    if act in {'target_raised', 'target_cut'} or (tp is not None and has_true_broker):
        return 'target_price_change'
    if has_watchlist and not has_true_broker:
        return 'market_watchlist_mention'
    if has_true_broker:
        if ANALYST_RE.search(body) and not BROKER_HOUSE_RE.search(body):
            return 'analyst_rating'
        if act in {'upgrade', 'downgrade'}:
            return 'upgrade_downgrade'
        if act in {'target_raised', 'target_cut'} or tp is not None:
            return 'target_price_change'
        if rate in {'positive', 'negative', 'neutral'}:
            return 'broker_rating'
        return 'analyst_rating'
    if raw.get('collector_source') in {'news_cache', 'news_feed', 'external_evidence', 'tv'}:
        return 'news_mention'
    return 'external_context'


def _mention_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'ticker': row.get('ticker'),
        'source': row.get('broker_house') or row.get('source') or 'External source',
        'headline': row.get('headline') or row.get('title'),
        'evidence_type': row.get('evidence_type'),
        'published_at': row.get('published_at'),
    }


def _apply_evidence_views(cached: dict[str, Any]) -> dict[str, Any]:
    """Rebuild consensus/market/external views from evidence_items."""
    out = dict(cached)
    evidence_items: list[dict[str, Any]] = []
    for row in out.get('evidence_items') or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        if not item.get('evidence_type'):
            text = _combined_text(item)
            item['evidence_type'] = classify_evidence_type(
                item,
                text=text,
                action=item.get('action'),
                rating=item.get('rating'),
                target_price=item.get('target_price'),
            )
        if item.get('evidence_type') == 'market_watchlist_mention':
            item['counts_toward_consensus'] = False
        else:
            item['counts_toward_consensus'] = item.get('evidence_type') in CONSENSUS_EVIDENCE_TYPES
        evidence_items.append(item)
    out['evidence_items'] = evidence_items

    market_watchlist_mentions: list[dict[str, Any]] = []
    external_evidence: list[dict[str, Any]] = []
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in evidence_items:
        ticker = str(row.get('ticker') or '').upper()
        if not ticker:
            continue
        by_ticker.setdefault(ticker, []).append(row)
        et = row.get('evidence_type')
        if et == 'market_watchlist_mention':
            market_watchlist_mentions.append(_mention_row(row))
        elif et in {'news_mention', 'external_context'}:
            external_evidence.append(_mention_row(row))

    consensus_by_ticker: dict[str, Any] = {}
    for ticker, rows in by_ticker.items():
        rated = [r for r in rows if r.get('evidence_type') in CONSENSUS_EVIDENCE_TYPES]
        if not rated:
            continue
        consensus_by_ticker[ticker] = {
            'ticker': ticker,
            **score_ticker_consensus(rated),
            'has_broker_consensus': True,
            'evidence': rated[:12],
        }

    scored_list = sorted(
        consensus_by_ticker.values(),
        key=lambda r: r.get('confidence_score', 0),
        reverse=True,
    )
    top_positive, top_negative, top_neutral = _split_consensus_buckets(scored_list)
    top_upgrades = [
        r for r in evidence_items
        if r.get('evidence_type') in CONSENSUS_EVIDENCE_TYPES
        and r.get('action') in {'upgrade', 'target_raised', 'positive_rating'}
    ][:8]
    top_downgrades = [
        r for r in evidence_items
        if r.get('evidence_type') in CONSENSUS_EVIDENCE_TYPES
        and r.get('action') in {'downgrade', 'target_cut', 'negative_rating'}
    ][:8]

    out.update({
        'consensus_by_ticker': consensus_by_ticker,
        'market_watchlist_mentions': market_watchlist_mentions[:12],
        'external_evidence': external_evidence[:12],
        'broker_rated_tickers': len(consensus_by_ticker),
        'market_mention_count': len(market_watchlist_mentions),
        'tracked_tickers': len(by_ticker),
        'tracked_ticker_names': sorted(by_ticker.keys()),
        'top_positive': top_positive,
        'top_negative': top_negative,
        'top_neutral': top_neutral,
        'top_upgrades': top_upgrades,
        'top_downgrades': top_downgrades,
        'target_price_changes': [
            r for r in evidence_items
            if r.get('evidence_type') in CONSENSUS_EVIDENCE_TYPES and r.get('target_price') is not None
        ][:12],
        'broker_mentions': evidence_items[:20],
        'impact_today': _impact_candidates(scored_list, mode='today'),
        'impact_tomorrow': _impact_candidates(scored_list, mode='tomorrow'),
    })
    return out


def extract_broker_evidence_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    rejected, reason = should_reject_item(raw)
    if rejected:
        return None
    text = _combined_text(raw)
    ticker = _normalize_ticker(raw.get('ticker') or raw.get('symbol'))
    if not ticker:
        return None
    rating = classify_rating(raw)
    action = detect_action(text)
    target_price, prev_target = extract_target_prices(text)
    if raw.get('target_price') is not None:
        target_price = _parse_float(raw.get('target_price')) or target_price
    if raw.get('previous_target') is not None:
        prev_target = _parse_float(raw.get('previous_target')) or prev_target
    broker_house = (
        raw.get('broker_house')
        or raw.get('broker_source')
        or raw.get('source')
        or extract_broker_house(text)
        or 'External source'
    )
    headline = _truncate_headline(str(raw.get('headline') or raw.get('title') or text[:160]))
    pub = raw.get('published_at') or raw.get('prediction_date') or raw.get('date')
    extracted_at = raw.get('extracted_at') or raw.get('collected_at') or _now_iso()
    if not pub:
        pub = extracted_at
    evidence_type = classify_evidence_type(
        raw, text=text, action=action, rating=rating, target_price=target_price,
    )
    return {
        'ticker': ticker,
        'broker_house': str(broker_house)[:80],
        'rating': rating,
        'action': action,
        'target_price': target_price,
        'previous_target': prev_target,
        'headline': headline,
        'published_at': pub,
        'extracted_at': extracted_at,
        'url': raw.get('url') or raw.get('link'),
        'classification': raw.get('classification') or 'broker_evidence',
        'source_type': raw.get('collector_source') or raw.get('source_type') or 'news',
        'evidence_type': evidence_type,
        'counts_toward_consensus': evidence_type in CONSENSUS_EVIDENCE_TYPES,
    }


def _append_unique_items(items: list[dict[str, Any]], rows: list[dict[str, Any]], *, source: str) -> None:
    seen: set[str] = {
        f"{_normalize_ticker(r.get('ticker') or r.get('symbol'))}|{str(r.get('headline') or r.get('title') or '')[:80]}"
        for r in items
        if isinstance(r, dict)
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = dict(row)
        payload.setdefault('collector_source', source)
        key = (
            f"{_normalize_ticker(payload.get('ticker') or payload.get('symbol'))}|"
            f"{str(payload.get('headline') or payload.get('title') or '')[:80]}"
        )
        if key in seen:
            continue
        seen.add(key)
        items.append(payload)


def _collect_raw_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    collector = _load_json_file(COLLECTOR_CACHE)
    _append_unique_items(items, [r for r in (collector.get('items') or []) if isinstance(r, dict)], source='collector')
    inbox = _load_json_file(INBOX_FILE)
    _append_unique_items(items, [r for r in (inbox.get('items') or []) if isinstance(r, dict)], source='inbox')
    consensus = _load_json_file(CONSENSUS_INBOX)
    _append_unique_items(items, [r for r in (consensus.get('items') or []) if isinstance(r, dict)], source='consensus_inbox')

    try:
        from backend.collectors.broker_app_collector import (
            collect_from_existing_news,
            collect_from_latest_market_data,
            get_external_evidence_dashboard,
        )

        _append_unique_items(items, collect_from_existing_news(limit=80), source='news_feed')
        _append_unique_items(items, collect_from_latest_market_data(limit=40), source='market_data')
        ext = get_external_evidence_dashboard() or {}
        _append_unique_items(
            items,
            [r for r in (ext.get('broker_candidates') or []) if isinstance(r, dict)],
            source='external_evidence',
        )
    except Exception as exc:
        _log(f'news/external collect fallback failed: {exc}')

    try:
        from backend.collectors.tv_intelligence_collector import load_cached_tv_intelligence

        tv = load_cached_tv_intelligence() or {}
        tv_rows = []
        for video in (tv.get('videos') or tv.get('items') or [])[:40]:
            if not isinstance(video, dict):
                continue
            tv_rows.append({
                'ticker': video.get('ticker') or video.get('symbol'),
                'headline': video.get('title') or video.get('headline'),
                'title': video.get('title'),
                'description': video.get('description'),
                'published_at': video.get('published_at') or video.get('date'),
                'source': video.get('channel') or 'TV Intelligence',
                'collector_source': 'tv',
            })
        _append_unique_items(items, tv_rows, source='tv')
    except Exception as exc:
        _log(f'tv collect fallback failed: {exc}')

    budget_cache = _load_json_file(get_data_path('budget_impact_cache.json'))
    budget_rows: list[dict[str, Any]] = []
    for row in (budget_cache.get('top_catalysts') or [])[:30]:
        if not isinstance(row, dict):
            continue
        headline = str(row.get('headline') or row.get('title') or '')
        if not headline:
            continue
        tickers = row.get('tickers') or row.get('named_companies') or []
        ticker = None
        if isinstance(tickers, list) and tickers:
            ticker = _normalize_ticker(tickers[0])
        budget_rows.append({
            'ticker': ticker,
            'headline': headline,
            'title': headline,
            'published_at': row.get('published_at') or budget_cache.get('generated_at'),
            'source': 'Budget catalyst',
            'collector_source': 'budget_news',
        })
    _append_unique_items(items, budget_rows, source='budget_news')

    existing = _load_json_file(CACHE_FILE)
    _append_unique_items(
        items,
        [r for r in (existing.get('evidence_items') or []) if isinstance(r, dict)],
        source='broker_cache_fallback',
    )

    for rel in ('news_feed.json', 'live_news_feed.json', 'govt_intelligence.json'):
        feed = _load_json_file(get_data_path(rel))
        articles = feed.get('articles') or feed.get('high_impact_items') or feed.get('items') or []
        feed_rows = []
        for art in articles[:40]:
            if not isinstance(art, dict):
                continue
            feed_rows.append({
                'ticker': art.get('ticker') or art.get('symbol'),
                'headline': art.get('title') or art.get('english_headline') or art.get('headline'),
                'title': art.get('title') or art.get('english_headline'),
                'published_at': art.get('published_at') or art.get('date'),
                'source': art.get('source') or rel.replace('.json', ''),
                'collector_source': 'news_cache',
            })
        _append_unique_items(items, feed_rows, source='news_cache')

    return items


def score_ticker_consensus(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = [
        row for row in evidence
        if row.get('evidence_type') in CONSENSUS_EVIDENCE_TYPES
        or row.get('counts_toward_consensus')
    ]
    if not evidence:
        return {
            'confidence_score': 0,
            'consensus_label': 'Unknown',
            'suggested_action': 'Research Only',
            'broker_counts': {'positive': 0, 'neutral': 0, 'negative': 0, 'unknown': 0},
            'latest_rating': None,
            'latest_action': None,
            'target_price': None,
            'previous_target': None,
            'freshness': 'unknown',
            'evidence': [],
            'source_count': 0,
        }

    score = 50.0
    counts = {'positive': 0, 'neutral': 0, 'negative': 0, 'unknown': 0}
    houses: set[str] = set()
    latest = sorted(
        evidence,
        key=lambda r: _evidence_timestamp(r) or datetime.min.replace(tzinfo=IST),
        reverse=True,
    )
    stale_penalty = 0.0

    for row in evidence:
        rating = row.get('rating') or 'unknown'
        counts[rating] = counts.get(rating, 0) + 1
        action = row.get('action')
        if rating == 'positive':
            score += 20
        elif rating == 'negative':
            score -= 30
        elif rating == 'neutral':
            score += 0
        if action == 'upgrade':
            score += 20
        elif action == 'downgrade':
            score -= 25
        elif action == 'target_raised':
            score += 15
        elif action == 'target_cut':
            score -= 20
        house = str(row.get('broker_house') or '').strip().lower()
        if house:
            houses.add(house)
        pub = _evidence_timestamp(row)
        if pub and (datetime.now(IST) - pub) > timedelta(days=7):
            stale_penalty += 5

    if len(houses) >= 2:
        score += 10

    score -= min(stale_penalty, 25)
    score = max(0, min(100, int(round(score))))
    label = consensus_label_from_score(score, counts)
    suggested = suggested_action_from_label(label, score)

    latest_row = latest[0]
    pub = _evidence_timestamp(latest_row)
    freshness = _freshness_from_timestamp(pub)

    return {
        'confidence_score': score,
        'consensus_label': label,
        'suggested_action': suggested,
        'broker_counts': counts,
        'latest_rating': latest_row.get('rating'),
        'latest_action': latest_row.get('action'),
        'target_price': latest_row.get('target_price'),
        'previous_target': latest_row.get('previous_target'),
        'freshness': freshness,
        'evidence': evidence[:12],
        'source_count': len(houses) or len(evidence),
    }


def consensus_label_from_score(score: int, counts: dict[str, int] | None = None) -> str:
    if score == 0 and counts and sum(counts.values()) == 0:
        return 'Unknown'
    pos = (counts or {}).get('positive', 0)
    neg = (counts or {}).get('negative', 0)
    if pos > 0 and neg > 0 and 40 <= score <= 59:
        return 'Mixed'
    if score >= 80:
        return 'Strong Positive'
    if score >= 60:
        return 'Positive'
    if score >= 40:
        return 'Neutral' if neg == 0 and pos == 0 else 'Mixed'
    if score >= 20:
        return 'Negative'
    return 'Avoid-Risk'


def suggested_action_from_label(label: str, score: int) -> str:
    if label in {'Strong Positive', 'Positive'}:
        return 'Watch for Confirmation'
    if label in {'Neutral', 'Mixed'}:
        return 'Research Only'
    if label == 'Negative':
        return 'Wait'
    if label == 'Avoid-Risk':
        return 'Avoid-Risk'
    return 'Research Only'


def _freshness_meta() -> dict[str, Any]:
    cache_age = _file_age_hours(CACHE_FILE)
    collector_age = _file_age_hours(COLLECTOR_CACHE)
    ages = [a for a in (cache_age, collector_age) if a is not None]
    max_age = max(ages) if ages else None
    if max_age is None:
        status = 'missing'
        stale_reason = 'no_cache'
    elif max_age <= 6:
        status = 'fresh'
        stale_reason = None
    elif max_age <= 24:
        status = 'aging'
        stale_reason = None
    else:
        status = 'stale'
        stale_reason = 'cache_older_than_24h'
    return {
        'status': status,
        'cache_age_hours': cache_age,
        'collector_age_hours': collector_age,
        'generated_at': _now_iso(),
        'stale_reason': stale_reason,
    }


POSITIVE_LABELS = frozenset({'Strong Positive', 'Positive'})
NEGATIVE_LABELS = frozenset({'Negative', 'Avoid-Risk'})


def _tracked_ticker_names(payload: dict[str, Any]) -> list[str]:
    consensus = payload.get('consensus_by_ticker') or {}
    if consensus:
        return sorted(str(k).upper() for k in consensus.keys())
    tickers: set[str] = set()
    for row in payload.get('evidence_items') or []:
        if isinstance(row, dict):
            sym = _normalize_ticker(row.get('ticker'))
            if sym:
                tickers.add(sym)
    return sorted(tickers)


def _consensus_primary_source(row: dict[str, Any]) -> str:
    evidence = row.get('evidence') or []
    if evidence and isinstance(evidence[0], dict):
        return str(
            evidence[0].get('broker_house')
            or evidence[0].get('source')
            or 'External source'
        )[:60]
    return 'External source'


def _consensus_primary_headline(row: dict[str, Any]) -> str:
    evidence = row.get('evidence') or []
    if evidence and isinstance(evidence[0], dict):
        return str(evidence[0].get('headline') or evidence[0].get('title') or '')[:120]
    return ''


def _split_consensus_buckets(
    scored_list: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    positive: list[dict[str, Any]] = []
    negative: list[dict[str, Any]] = []
    neutral: list[dict[str, Any]] = []
    for row in scored_list:
        label = str(row.get('consensus_label') or 'Unknown')
        score = int(row.get('confidence_score') or 0)
        if label in POSITIVE_LABELS or (score >= 60 and label not in NEGATIVE_LABELS):
            positive.append(row)
        elif label in NEGATIVE_LABELS or score < 40:
            negative.append(row)
        else:
            neutral.append(row)
    return positive[:8], negative[:8], neutral[:8]


def _enrich_cache_buckets(cached: dict[str, Any]) -> dict[str, Any]:
    if not cached:
        return cached
    return _apply_evidence_views(cached)


def _format_neutral_overview_lines(rows: list[dict[str, Any]], *, limit: int = 6) -> list[str]:
    lines: list[str] = []
    for row in rows[:limit]:
        ticker = row.get('ticker') or '—'
        label = row.get('consensus_label') or 'Unknown'
        score = row.get('confidence_score', '—')
        source = _consensus_primary_source(row)
        lines.append(f'• {ticker} — {label} · score {score} · {source}')
        headline = _consensus_primary_headline(row)
        if headline:
            lines.append(f'  Evidence: {headline[:90]}')
    return lines


def build_broker_intelligence_cache() -> dict[str, Any]:
    raw_items = _collect_raw_items()
    evidence_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        extracted = extract_broker_evidence_item(raw)
        if not extracted:
            continue
        key = f"{extracted['ticker']}|{extracted.get('headline', '')[:80]}|{extracted.get('broker_house')}"
        if key in seen:
            continue
        seen.add(key)
        evidence_items.append(extracted)

    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in evidence_items:
        by_ticker.setdefault(row['ticker'], []).append(row)

    freshness = _freshness_meta()
    source_counts: dict[str, int] = {}
    for row in evidence_items:
        src = str(row.get('broker_house') or 'unknown')
        source_counts[src] = source_counts.get(src, 0) + 1

    payload: dict[str, Any] = {
        'ok': True,
        'stage': STAGE,
        'engine': ENGINE_NAME,
        'generated_at': _now_iso(),
        'refreshed_at': _now_iso(),
        'freshness': freshness,
        'source_counts': source_counts,
        'evidence_items': evidence_items,
        'stale_reason': freshness.get('stale_reason'),
        'disclaimer': 'External broker/app evidence — not our final prediction.',
    }
    return _apply_evidence_views(payload)


def _impact_candidates(scored_list: list[dict[str, Any]], *, mode: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in scored_list:
        score = int(row.get('confidence_score') or 0)
        label = row.get('consensus_label') or 'Unknown'
        if score >= 60 and label in {'Strong Positive', 'Positive'}:
            out.append({
                'ticker': row.get('ticker'),
                'consensus_label': label,
                'confidence_score': score,
                'suggested_action': row.get('suggested_action'),
                'mode': mode,
                'impact': 'supportive_evidence',
            })
        elif score < 40 or label in {'Negative', 'Avoid-Risk'}:
            out.append({
                'ticker': row.get('ticker'),
                'consensus_label': label,
                'confidence_score': score,
                'suggested_action': row.get('suggested_action'),
                'mode': mode,
                'impact': 'risk_flag',
            })
        if len(out) >= 6:
            break
    return out


def refresh_broker_intelligence(*, persist: bool = True) -> dict[str, Any]:
    payload = build_broker_intelligence_cache()
    payload['ok'] = True
    if persist:
        _save_cache(payload)
        verify = verify_broker_cache_write()
        payload['cache_verify'] = verify
        if not verify.get('ok'):
            payload['ok'] = False
            payload['stale_reason'] = verify.get('error')
        _log(
            f"refreshed tickers={payload.get('tracked_tickers')} "
            f"evidence={len(payload.get('evidence_items') or [])} "
            f"verify={verify.get('ok')}"
        )
    return payload


def format_broker_refresh_telegram(result: dict[str, Any] | None = None) -> str:
    result = result or {}
    verify = result.get('cache_verify') or {}
    if result.get('ok') is False or (verify and not verify.get('ok')):
        err = verify.get('error') or result.get('stale_reason') or 'cache_write_failed'
        return _sanitize_text(
            '<b>🏦 Broker refresh</b>\n\n'
            f'Broker refresh failed ({err}).\n'
            '<i>Research only — retry /broker refresh.</i>'
        )

    evidence_count = int(
        (verify or {}).get('evidence_count')
        or len(result.get('evidence_items') or [])
    )
    ticker_count = int(
        (verify or {}).get('ticker_count')
        or result.get('tracked_tickers')
        or len(result.get('tracked_ticker_names') or [])
        or len(result.get('consensus_by_ticker') or {})
        or 0
    )
    broker_rated = int(result.get('broker_rated_tickers') or len(result.get('consensus_by_ticker') or {}))
    market_mentions = int(result.get('market_mention_count') or len(result.get('market_watchlist_mentions') or []))

    if evidence_count <= 0:
        return _sanitize_text(
            '<b>🏦 Broker refresh</b>\n\n'
            'Broker refresh completed but no fresh broker evidence found.\n'
            '<i>Research only.</i>'
        )

    tickers = result.get('tracked_ticker_names') or _tracked_ticker_names(result)
    ticker_line = ', '.join(tickers[:8]) if tickers else '—'
    drill = tickers[0] if tickers else 'TICKER'
    return _sanitize_text(
        '<b>🏦 Broker refresh</b>\n\n'
        'Broker refresh completed.\n'
        f'Broker-rated tickers: {broker_rated}\n'
        f'Market/news mentions: {market_mentions}\n'
        f'Evidence: {evidence_count}\n'
        f'Tickers: {ticker_line}\n'
        f'Use /broker {drill} for drilldown.\n'
        '<i>Research only — market mentions are not broker ratings.</i>'
    )


def _missing_lite() -> dict[str, Any]:
    return {
        'ok': True,
        'lite': True,
        'cache_missing': True,
        'stale': True,
        'stage': STAGE,
        'engine': ENGINE_NAME,
        'generated_at': _now_iso(),
        'message': MISSING_MESSAGE,
        'freshness': {'status': 'missing'},
        'tracked_tickers': 0,
        'top_positive': [],
        'top_negative': [],
        'top_neutral': [],
        'tracked_ticker_names': [],
        'consensus_by_ticker': {},
        'evidence_items': [],
        'disclaimer': 'External broker/app evidence — not our final prediction.',
    }


def _lite_from_cache(cached: dict[str, Any]) -> dict[str, Any]:
    fresh = cached.get('freshness') or {}
    stale = fresh.get('status') in {'stale', 'missing'} or bool(cached.get('stale_reason'))
    return {
        'ok': True,
        'lite': True,
        'from_cache': True,
        'cache_missing': False,
        'stale': stale,
        'stage': STAGE,
        'engine': ENGINE_NAME,
        'generated_at': cached.get('generated_at'),
        'message': cached.get('message'),
        'freshness': fresh,
        'tracked_tickers': cached.get('tracked_tickers') or len(cached.get('consensus_by_ticker') or {}),
        'source_counts': cached.get('source_counts') or {},
        'top_positive': (cached.get('top_positive') or [])[:8],
        'top_negative': (cached.get('top_negative') or [])[:8],
        'top_neutral': (cached.get('top_neutral') or [])[:8],
        'tracked_ticker_names': (cached.get('tracked_ticker_names') or _tracked_ticker_names(cached))[:12],
        'market_watchlist_mentions': (cached.get('market_watchlist_mentions') or [])[:12],
        'external_evidence': (cached.get('external_evidence') or [])[:12],
        'broker_rated_tickers': cached.get('broker_rated_tickers') or len(cached.get('consensus_by_ticker') or {}),
        'market_mention_count': cached.get('market_mention_count') or len(cached.get('market_watchlist_mentions') or []),
        'top_upgrades': (cached.get('top_upgrades') or [])[:6],
        'top_downgrades': (cached.get('top_downgrades') or [])[:6],
        'target_price_changes': (cached.get('target_price_changes') or [])[:6],
        'impact_today': (cached.get('impact_today') or [])[:4],
        'impact_tomorrow': (cached.get('impact_tomorrow') or [])[:4],
        'evidence_items': (cached.get('evidence_items') or [])[:12],
        'broker_mentions': (cached.get('broker_mentions') or [])[:8],
        'stale_reason': cached.get('stale_reason'),
        'disclaimer': cached.get('disclaimer') or 'External broker/app evidence — not our final prediction.',
    }


def get_broker_intel_overview(*, cache_only: bool = False, lite: bool = False) -> dict[str, Any]:
    if cache_only:
        cached = _load_cache()
        if cached and (_cache_exists_on_disk() or cached.get('ok')):
            cached = _enrich_cache_buckets(cached)
            if lite:
                return _lite_from_cache(cached)
            out = dict(cached)
            out['from_cache'] = True
            out['cache_missing'] = False
            return _enrich_cache_buckets(out)
        return _missing_lite()

    return refresh_broker_intelligence(persist=True)


def get_broker_intel_ticker(ticker: str, *, cache_only: bool = True, lite: bool = False) -> dict[str, Any]:
    sym = _normalize_ticker(ticker)
    if not sym:
        return {'ok': False, 'error': 'invalid_ticker', 'ticker': ticker}

    cached = _load_cache()
    if not cached or not (_cache_exists_on_disk() or cached.get('ok')):
        if cache_only:
            return {
                'ok': True,
                'cache_missing': True,
                'lite': lite,
                'ticker': sym,
                'message': MISSING_MESSAGE,
            }
        cached = refresh_broker_intelligence(persist=True)

    consensus = (cached.get('consensus_by_ticker') or {}).get(sym)
    all_rows = [
        r for r in (cached.get('evidence_items') or [])
        if _normalize_ticker(r.get('ticker')) == sym
    ]
    watchlist_rows = [r for r in all_rows if r.get('evidence_type') == 'market_watchlist_mention']

    if not consensus and not all_rows:
        return {
            'ok': True,
            'cache_missing': False,
            'lite': lite,
            'ticker': sym,
            'found': False,
            'message': f'No broker intelligence for {sym}.',
        }

    if not consensus and watchlist_rows:
        return {
            'ok': True,
            'lite': lite,
            'from_cache': True,
            'ticker': sym,
            'found': True,
            'watchlist_only': True,
            'has_broker_consensus': False,
            'market_mentions': [_mention_row(r) for r in watchlist_rows[:6]],
            'freshness': cached.get('freshness') or {},
            'disclaimer': cached.get('disclaimer') or 'External broker/app evidence — not our final prediction.',
        }

    if not consensus:
        return {
            'ok': True,
            'cache_missing': False,
            'lite': lite,
            'ticker': sym,
            'found': False,
            'message': f'No broker intelligence for {sym}.',
        }

    out = {
        'ok': True,
        'lite': lite,
        'from_cache': True,
        'ticker': sym,
        'found': True,
        'has_broker_consensus': True,
        'watchlist_only': False,
        'consensus': consensus,
        'freshness': cached.get('freshness') or {},
        'impact_today': next(
            (r for r in (cached.get('impact_today') or []) if r.get('ticker') == sym),
            None,
        ),
        'impact_tomorrow': next(
            (r for r in (cached.get('impact_tomorrow') or []) if r.get('ticker') == sym),
            None,
        ),
        'disclaimer': cached.get('disclaimer') or 'External broker/app evidence — not our final prediction.',
    }
    if lite:
        out['evidence'] = (consensus.get('evidence') or [])[:6]
    return out


def get_broker_intel_evidence(*, cache_only: bool = True, lite: bool = False) -> dict[str, Any]:
    cached = _load_cache()
    if not cached or not (_cache_exists_on_disk() or cached.get('ok')):
        if cache_only:
            return {
                'ok': True,
                'cache_missing': True,
                'lite': lite,
                'message': MISSING_MESSAGE,
                'evidence_items': [],
            }
        cached = refresh_broker_intelligence(persist=True)

    items = cached.get('evidence_items') or []
    limit = 12 if lite else 30
    return {
        'ok': True,
        'lite': lite,
        'from_cache': True,
        'cache_missing': False,
        'freshness': cached.get('freshness') or {},
        'evidence_items': items[:limit],
        'broker_mentions': (cached.get('broker_mentions') or [])[:limit],
        'disclaimer': cached.get('disclaimer') or 'External broker/app evidence — not our final prediction.',
    }


def format_broker_overview_telegram() -> str:
    overview = get_broker_intel_overview(cache_only=True, lite=False)
    if overview.get('cache_missing') and not _cache_exists_on_disk():
        return _sanitize_text(
            '<b>🏦 Broker Intelligence</b>\n\n'
            'Freshness: <code>missing</code>\n'
            'Broker-rated tickers: 0\n\n'
            'Broker cache unavailable.\n'
            '<i>Research only — use /broker refresh to rebuild.</i>'
        )

    fresh = overview.get('freshness') or {}
    broker_rated = int(overview.get('broker_rated_tickers') or len(overview.get('consensus_by_ticker') or {}))
    market_mentions = int(overview.get('market_mention_count') or len(overview.get('market_watchlist_mentions') or []))
    fresh_status = fresh.get('status') or 'unknown'
    lines = [
        '<b>🏦 Broker Intelligence</b>',
        '',
        f"Freshness: <code>{fresh_status}</code>",
        f"Broker-rated tickers: {broker_rated}",
        f"Market/news mentions: {market_mentions}",
    ]
    if overview.get('stale_reason'):
        lines.append(f"Note: {overview.get('stale_reason')}")

    lines.extend(['', '<b>Broker/Analyst consensus:</b>'])
    top_pos = overview.get('top_positive') or []
    top_neg = overview.get('top_negative') or []
    if top_pos or top_neg:
        for row in top_pos[:4]:
            lines.append(
                f"• {row.get('ticker')} · {row.get('consensus_label')} "
                f"({row.get('confidence_score')}) · {row.get('suggested_action')}"
            )
        for row in top_neg[:4]:
            lines.append(
                f"• {row.get('ticker')} · {row.get('consensus_label')} "
                f"({row.get('confidence_score')}) · {row.get('suggested_action')}"
            )
    else:
        lines.append('• No broker/analyst ratings found.')

    lines.extend(['', '<b>Market watchlist mentions:</b>'])
    watchlist = overview.get('market_watchlist_mentions') or []
    if watchlist:
        for row in watchlist[:6]:
            ticker = row.get('ticker') or '—'
            source = row.get('source') or 'External source'
            headline = _truncate_headline(str(row.get('headline') or ''))
            lines.append(f'• {ticker} — {source}')
            if headline:
                lines.append(f'  {headline}')
    else:
        lines.append('• None in cache')

    lines.extend(['', '<b>External evidence:</b>'])
    external = overview.get('external_evidence') or []
    if external:
        for row in external[:4]:
            ticker = row.get('ticker') or '—'
            source = row.get('source') or 'External source'
            headline = _truncate_headline(str(row.get('headline') or ''))
            lines.append(f'• {ticker} · {source} · {headline}')
    else:
        lines.append('• None in cache')

    lines.extend([
        '',
        '<i>Research only — market mentions are not broker ratings.</i>',
    ])
    return _sanitize_text('\n'.join(lines))


def format_broker_evidence_telegram() -> str:
    overview = get_broker_intel_overview(cache_only=True, lite=False)
    if overview.get('cache_missing') and not _cache_exists_on_disk():
        return _sanitize_text(
            '<b>🏦 Broker evidence</b>\n\n'
            f'{MISSING_MESSAGE}\n'
            '<i>Research only — use /broker refresh.</i>'
        )

    items = overview.get('evidence_items') or []
    consensus = overview.get('consensus_by_ticker') or {}
    if not items:
        return _sanitize_text(
            '<b>🏦 Broker evidence</b>\n\n'
            'No fresh broker evidence found.\n'
            '<i>Research only.</i>'
        )

    lines = ['<b>🏦 Broker evidence</b>', '', '<b>Latest evidence:</b>']
    for row in items[:8]:
        if not isinstance(row, dict):
            continue
        ticker = row.get('ticker') or '—'
        c_row = consensus.get(str(ticker).upper()) or {}
        label = c_row.get('consensus_label') or row.get('rating') or row.get('evidence_type') or 'Unknown'
        source = row.get('broker_house') or row.get('source') or 'External source'
        headline = _truncate_headline(str(row.get('headline') or row.get('title') or '—'))
        freshness = (
            c_row.get('freshness')
            or row.get('freshness')
            or _freshness_from_timestamp(_evidence_timestamp(row))
        )
        etype = row.get('evidence_type') or 'unknown'
        lines.append(f'• {ticker} · {label} · {source}')
        lines.append(f'  {headline}')
        lines.append(f'  Type: {etype} · Freshness: {freshness}')

    lines.extend(['', '<i>Research only — not a trade signal.</i>'])
    return _sanitize_text('\n'.join(lines))


def format_broker_ticker_telegram(ticker: str) -> str:
    detail = get_broker_intel_ticker(ticker, cache_only=True, lite=True)
    sym = detail.get('ticker') or _normalize_ticker(ticker)
    if detail.get('cache_missing'):
        return _sanitize_text(f'<b>🏦 Broker — {sym}</b>\n\n{MISSING_MESSAGE}')
    if not detail.get('found'):
        cached = _load_cache()
        tickers = _tracked_ticker_names(cached) if cached else []
        lines = [
            f'<b>🏦 Broker — {sym}</b>',
            '',
            f'No broker intelligence for {sym}.',
        ]
        if tickers:
            lines.append('Available tracked tickers:')
            for name in tickers[:8]:
                lines.append(f'• {name}')
            lines.append(f'Use /broker {tickers[0]}')
        else:
            lines.append('Use /broker refresh to rebuild cache.')
        lines.append('<i>Research only.</i>')
        return _sanitize_text('\n'.join(lines))

    if detail.get('watchlist_only'):
        mention = (detail.get('market_mentions') or [{}])[0]
        headline = str(mention.get('headline') or '')[:120]
        source = mention.get('source') or 'External source'
        lines = [
            f'<b>🏦 Broker — {sym}</b>',
            '',
            'Evidence type: Market watchlist mention',
            'Broker consensus: Not available',
            'This is not a broker rating.',
            'Stance: Research Only',
            f'Source: {source}',
        ]
        if headline:
            lines.append(f'Headline: {headline[:90]}')
        lines.extend(['', '<i>Research only — confirm with price + volume.</i>'])
        return _sanitize_text('\n'.join(lines))

    c = detail.get('consensus') or {}
    lines = [
        f'<b>🏦 Broker — {sym}</b>',
        '',
        f"Consensus: <b>{c.get('consensus_label', 'Unknown')}</b>",
        f"Score: {c.get('confidence_score', '—')} · Freshness: {c.get('freshness', '—')}",
        f"Suggested: {c.get('suggested_action', 'Research Only')}",
    ]
    if c.get('latest_action'):
        lines.append(f"Latest action: {c.get('latest_action')}")
    if c.get('target_price') is not None:
        tp = c.get('target_price')
        prev = c.get('previous_target')
        if prev is not None:
            lines.append(f'Target: {tp} (prev {prev})')
        else:
            lines.append(f'Target: {tp}')

    counts = c.get('broker_counts') or {}
    lines.append(
        f"Sources: +{counts.get('positive', 0)} / ={counts.get('neutral', 0)} / -{counts.get('negative', 0)}"
    )

    lines.extend(['', '<b>Evidence:</b>'])
    for row in (detail.get('evidence') or c.get('evidence') or [])[:4]:
        headline = str(row.get('headline') or '—')[:90]
        house = row.get('broker_house') or '—'
        lines.append(f'• {house}: {headline}')

    for key, label in (('impact_today', 'Today impact'), ('impact_tomorrow', 'Tomorrow impact')):
        impact = detail.get(key)
        if impact:
            lines.append(f'{label}: {impact.get("impact")} · {impact.get("suggested_action")}')

    lines.extend(['', '<i>External evidence only — not a trade signal.</i>'])
    return _sanitize_text('\n'.join(lines))


def handle_broker_command(args: str) -> str:
    raw = str(args or '').strip()
    if not raw:
        return format_broker_overview_telegram()
    parts = raw.split(maxsplit=1)
    sub = parts[0].lower()
    if sub in {'overview', 'summary'}:
        return format_broker_overview_telegram()
    if sub == 'refresh':
        result = refresh_broker_intelligence(persist=True)
        return format_broker_refresh_telegram(result)
    if sub == 'evidence':
        return format_broker_evidence_telegram()
    return format_broker_ticker_telegram(sub.upper() if sub.isalpha() else parts[0])


def broker_decision_bullets(ticker: str, *, mode: str = 'today') -> list[str]:
    """Evidence-only bullets for /today and /tomorrow — not trade signals."""
    sym = _normalize_ticker(ticker)
    if not sym:
        return []
    cached = _load_cache()
    if not cached or not (_cache_exists_on_disk() or cached.get('ok')):
        return []
    evidence_items = cached.get('evidence_items') or []
    if not evidence_items and not (cached.get('consensus_by_ticker') or {}):
        return []
    detail = get_broker_intel_ticker(sym, cache_only=True, lite=True)
    if not detail.get('found'):
        return []
    if detail.get('watchlist_only') or not detail.get('has_broker_consensus'):
        return []
    c = detail.get('consensus') or {}
    label = c.get('consensus_label') or 'Unknown'
    score = int(c.get('confidence_score') or 0)
    bullets: list[str] = []
    if score >= 60 and label in {'Strong Positive', 'Positive'}:
        bullets.append(f'Broker consensus supports {sym}')
    elif score < 40 or label in {'Negative', 'Avoid-Risk'}:
        action = c.get('latest_action')
        if action in {'downgrade', 'target_cut', 'negative_rating'}:
            bullets.append(f'Broker consensus conflict / downgrade risk on {sym}')
        else:
            bullets.append(f'Broker consensus conflict / downgrade risk on {sym}')
    return bullets


def broker_supports_ticker(ticker: str) -> bool:
    sym = _normalize_ticker(ticker)
    if not sym:
        return False
    cached = _load_cache()
    row = (cached.get('consensus_by_ticker') or {}).get(sym) if cached else None
    if not row:
        return False
    return int(row.get('confidence_score') or 0) >= 60


def broker_conflicts_ticker(ticker: str) -> bool:
    sym = _normalize_ticker(ticker)
    if not sym:
        return False
    cached = _load_cache()
    row = (cached.get('consensus_by_ticker') or {}).get(sym) if cached else None
    if not row:
        return False
    label = row.get('consensus_label') or ''
    score = int(row.get('confidence_score') or 0)
    return score < 40 or label in {'Negative', 'Avoid-Risk'}
