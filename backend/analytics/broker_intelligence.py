"""
AstraEdge Broker Intelligence — Stage 48L.

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
STAGE = '48L'
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
    return _load_json_file(CACHE_FILE)


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
    headline = str(raw.get('headline') or raw.get('title') or text[:160])
    pub = raw.get('published_at') or raw.get('prediction_date') or raw.get('date')
    return {
        'ticker': ticker,
        'broker_house': str(broker_house)[:80],
        'rating': rating,
        'action': action,
        'target_price': target_price,
        'previous_target': prev_target,
        'headline': headline[:200],
        'published_at': pub,
        'url': raw.get('url') or raw.get('link'),
        'classification': raw.get('classification') or 'broker_evidence',
        'source_type': raw.get('collector_source') or raw.get('source_type') or 'news',
    }


def _collect_raw_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    collector = _load_json_file(COLLECTOR_CACHE)
    for row in collector.get('items') or []:
        if isinstance(row, dict):
            items.append(row)
    inbox = _load_json_file(INBOX_FILE)
    for row in inbox.get('items') or []:
        if isinstance(row, dict):
            items.append(row)
    consensus = _load_json_file(CONSENSUS_INBOX)
    for row in consensus.get('items') or []:
        if isinstance(row, dict):
            items.append(row)
    return items


def score_ticker_consensus(evidence: list[dict[str, Any]]) -> dict[str, Any]:
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
        key=lambda r: _parse_date(r.get('published_at')) or datetime.min.replace(tzinfo=IST),
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
        pub = _parse_date(row.get('published_at'))
        if pub and (datetime.now(IST) - pub) > timedelta(days=7):
            stale_penalty += 5

    if len(houses) >= 2:
        score += 10

    score -= min(stale_penalty, 25)
    score = max(0, min(100, int(round(score))))
    label = consensus_label_from_score(score, counts)
    suggested = suggested_action_from_label(label, score)

    latest_row = latest[0]
    pub = _parse_date(latest_row.get('published_at'))
    if pub and (datetime.now(IST) - pub) <= timedelta(hours=24):
        freshness = 'fresh'
    elif pub and (datetime.now(IST) - pub) <= timedelta(days=7):
        freshness = 'aging'
    else:
        freshness = 'stale'

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

    consensus_by_ticker: dict[str, Any] = {}
    for ticker, rows in by_ticker.items():
        consensus_by_ticker[ticker] = {'ticker': ticker, **score_ticker_consensus(rows)}

    scored_list = sorted(
        consensus_by_ticker.values(),
        key=lambda r: r.get('confidence_score', 0),
        reverse=True,
    )
    top_upgrades = [
        r for r in evidence_items if r.get('action') in {'upgrade', 'target_raised', 'positive_rating'}
    ][:8]
    top_downgrades = [
        r for r in evidence_items if r.get('action') in {'downgrade', 'target_cut', 'negative_rating'}
    ][:8]
    target_price_changes = [
        r for r in evidence_items if r.get('target_price') is not None
    ][:12]

    source_counts: dict[str, int] = {}
    for row in evidence_items:
        src = str(row.get('broker_house') or 'unknown')
        source_counts[src] = source_counts.get(src, 0) + 1

    freshness = _freshness_meta()
    payload: dict[str, Any] = {
        'ok': True,
        'stage': STAGE,
        'engine': ENGINE_NAME,
        'generated_at': _now_iso(),
        'refreshed_at': _now_iso(),
        'freshness': freshness,
        'source_counts': source_counts,
        'consensus_by_ticker': consensus_by_ticker,
        'top_upgrades': top_upgrades,
        'top_downgrades': top_downgrades,
        'target_price_changes': target_price_changes,
        'broker_mentions': evidence_items[:20],
        'evidence_items': evidence_items,
        'stale_reason': freshness.get('stale_reason'),
        'tracked_tickers': len(consensus_by_ticker),
        'top_positive': [r for r in scored_list if r.get('confidence_score', 0) >= 60][:8],
        'top_negative': sorted(
            [r for r in scored_list if r.get('confidence_score', 0) < 40],
            key=lambda r: r.get('confidence_score', 0),
        )[:8],
        'impact_today': _impact_candidates(scored_list, mode='today'),
        'impact_tomorrow': _impact_candidates(scored_list, mode='tomorrow'),
        'disclaimer': 'External broker/app evidence — not our final prediction.',
    }
    return payload


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
    if persist:
        _save_cache(payload)
        _log(
            f"refreshed tickers={payload.get('tracked_tickers')} "
            f"evidence={len(payload.get('evidence_items') or [])}"
        )
    return payload


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
    if cache_only and lite:
        cached = _load_cache()
        if cached and cached.get('ok'):
            return _lite_from_cache(cached)
        return _missing_lite()

    if cache_only:
        cached = _load_cache()
        if cached and cached.get('ok'):
            out = dict(cached)
            out['from_cache'] = True
            return out
        return _missing_lite()

    return refresh_broker_intelligence(persist=True)


def get_broker_intel_ticker(ticker: str, *, cache_only: bool = True, lite: bool = False) -> dict[str, Any]:
    sym = _normalize_ticker(ticker)
    if not sym:
        return {'ok': False, 'error': 'invalid_ticker', 'ticker': ticker}

    cached = _load_cache()
    if not cached or not cached.get('ok'):
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
    if not cached or not cached.get('ok'):
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
    if overview.get('cache_missing'):
        cached = _load_cache()
        if not cached:
            return _sanitize_text(
                '<b>🏦 Broker intelligence</b>\n\n'
                'Freshness: <code>missing</code>\n'
                'Tracked tickers: 0\n\n'
                'Broker cache unavailable.\n'
                '<i>Research only — use /broker refresh to rebuild.</i>'
            )
        overview = cached

    fresh = overview.get('freshness') or {}
    lines = [
        '<b>🏦 Broker intelligence</b>',
        '',
        f"Freshness: <code>{fresh.get('status', 'unknown')}</code>",
        f"Tracked tickers: {overview.get('tracked_tickers') or len(overview.get('consensus_by_ticker') or {})}",
    ]
    if overview.get('stale_reason'):
        lines.append(f"Note: {overview.get('stale_reason')}")

    lines.extend(['', '<b>Top positive:</b>'])
    top_pos = overview.get('top_positive') or []
    if top_pos:
        for row in top_pos[:5]:
            lines.append(
                f"• {row.get('ticker')} · {row.get('consensus_label')} "
                f"({row.get('confidence_score')}) · {row.get('suggested_action')}"
            )
    else:
        lines.append('• None in cache')

    lines.extend(['', '<b>Top negative / risk:</b>'])
    top_neg = overview.get('top_negative') or []
    if top_neg:
        for row in top_neg[:5]:
            lines.append(
                f"• {row.get('ticker')} · {row.get('consensus_label')} "
                f"({row.get('confidence_score')}) · {row.get('suggested_action')}"
            )
    else:
        lines.append('• None flagged')

    impact = overview.get('impact_today') or []
    if impact:
        lines.extend(['', '<b>Impact on today:</b>'])
        for row in impact[:3]:
            lines.append(
                f"• {row.get('ticker')} · {row.get('impact')} · {row.get('suggested_action')}"
            )

    impact_t = overview.get('impact_tomorrow') or []
    if impact_t:
        lines.extend(['', '<b>Impact on tomorrow:</b>'])
        for row in impact_t[:3]:
            lines.append(
                f"• {row.get('ticker')} · {row.get('impact')} · {row.get('suggested_action')}"
            )

    lines.extend([
        '',
        '<i>Research only — watch/confirm. Use /broker RELIANCE or /broker refresh.</i>',
    ])
    return _sanitize_text('\n'.join(lines))


def format_broker_ticker_telegram(ticker: str) -> str:
    detail = get_broker_intel_ticker(ticker, cache_only=True, lite=True)
    sym = detail.get('ticker') or _normalize_ticker(ticker)
    if detail.get('cache_missing'):
        return _sanitize_text(f'<b>🏦 Broker — {sym}</b>\n\n{MISSING_MESSAGE}')
    if not detail.get('found'):
        return _sanitize_text(f'<b>🏦 Broker — {sym}</b>\n\nNo broker intelligence for this ticker.')

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
        refresh_broker_intelligence(persist=True)
        return _sanitize_text(
            '<b>🏦 Broker refresh</b>\n\nBroker intelligence cache rebuild started/completed.\n'
            '<i>Research only — use /broker for overview.</i>'
        )
    return format_broker_ticker_telegram(sub.upper() if sub.isalpha() else parts[0])


def broker_decision_bullets(ticker: str, *, mode: str = 'today') -> list[str]:
    """Evidence-only bullets for /today and /tomorrow — not trade signals."""
    sym = _normalize_ticker(ticker)
    if not sym:
        return []
    detail = get_broker_intel_ticker(sym, cache_only=True, lite=True)
    if not detail.get('found'):
        return []
    c = detail.get('consensus') or {}
    label = c.get('consensus_label') or 'Unknown'
    score = int(c.get('confidence_score') or 0)
    bullets: list[str] = []
    if score >= 60 and label in {'Strong Positive', 'Positive'}:
        bullets.append(
            f'Broker evidence supports {sym} ({label}, score {score}) — watch for confirmation'
        )
    elif score < 40 or label in {'Negative', 'Avoid-Risk'}:
        action = c.get('latest_action')
        suffix = f' ({action})' if action in {'downgrade', 'target_cut', 'negative_rating'} else ''
        bullets.append(f'Broker conflict/risk on {sym}{suffix} — {c.get("suggested_action", "Wait")}')
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
